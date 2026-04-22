"""Bridge: Extract L1 memory objects from a meeting transcript and insert into
the temporal memory tree."""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from gemini_clients import create_gemini_client
from importance import (
    IMPORTANCE_SCALE,
    MIN_IMPORTANCE_THRESHOLD,
    calibrate_l1_importance,
)
from io_utils import load_api_keys, load_tree, print_json_safe, save_json, utc_now_iso
from schema import BRIDGE_RESPONSE_SCHEMA, DEFAULT_MODEL_NAME, MEMORY_OBJ_TYPES

TODO_PREFIXES = ("需要", "待辦", "應", "計劃", "必須")


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def build_bridge_prompt(
    transcript: str,
    meeting_id: str,
    existing_topics: list[str],
) -> str:
    topics_str = ", ".join(existing_topics) if existing_topics else "(尚無)"
    return f"""
你是一個「長期記憶擷取器」。
任務：從單次會議逐字稿中，擷取所有重要的記憶物件，分類為
decision / todo / method_change / result / open_question / argument。

規則：
1) 回傳 JSON only，不要有任何額外文字。
2) 每個記憶物件必須有 type、content、importance、evidence、related_topics。
3) type 含義：
   - decision：會議中做出的決策或結論
   - todo：被指派或提及的待辦事項
   - method_change：方法論、演算法、流程的變更
   - result：實驗結果、發現、觀察報告
   - open_question：尚未解決的研究問題
   - argument：決策背後的論點與推理
4) importance 評分標準（0.0~1.0，請對齊這個尺度）：
{IMPORTANCE_SCALE}
4.1) Importance calibration guidelines（請盡量對齊）：
   - decision / method_change 影響多人或跨會議者：0.7~0.9
   - decision / method_change 僅影響單一會議：0.5~0.7
   - todo 已有明確負責人且影響後續實驗設計：0.6~0.7
   - todo 瑣碎或模糊（如「考慮借標籤機」）：0.3~0.4
   - open_question 表示「問題存在」但無需立即解答：0.3~0.5
   - open_question 阻擋後續決策、需盡快釐清：0.6~0.8
   - result 直接影響後續實驗或錄音品質：0.7~0.8
   - result 背景資訊、非關鍵：0.4~0.5
   - argument 強力支撐某決策：0.5~0.7
   - argument 一般討論觀點：0.3~0.5
5) evidence 請引用逐字稿中的關鍵句子（簡短即可）。
6) related_topics 列出相關主題關鍵字，用於後續跨會議的因果鏈追蹤。
   已知主題關鍵字（供參考，可新增）：{topics_str}
7) 請盡量完整擷取，不要遺漏重要內容，但也不要重複。
8) 文字欄位請優先使用繁體中文。

會議 ID：{meeting_id}

逐字稿：
{transcript}
""".strip()


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def extract_json(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        raise RuntimeError("Response does not contain valid JSON object.")
    candidate = text[start : end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse JSON output.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("JSON output must be an object.")
    return data


def call_gemini_bridge(
    model_name: str,
    api_key: str | list[str],
    transcript: str,
    meeting_id: str,
    existing_topics: list[str],
    max_retries: int = 6,
) -> dict[str, Any]:
    def _is_retryable_error(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code in {429, 500, 502, 503, 504}:
            return True

        msg = str(exc).upper()
        retry_tokens = (
            "429",
            "500",
            "502",
            "503",
            "504",
            "RESOURCE_EXHAUSTED",
            "UNAVAILABLE",
            "RATE LIMIT",
        )
        return any(token in msg for token in retry_tokens)

    client = create_gemini_client(api_key)
    prompt = build_bridge_prompt(transcript, meeting_id, existing_topics)
    config = {
        "temperature": 0.15,
        "response_mime_type": "application/json",
        "response_json_schema": BRIDGE_RESPONSE_SCHEMA,
    }

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            return extract_json(response.text or "")
        except Exception as exc:
            if attempt >= max_retries or not _is_retryable_error(exc):
                raise

            backoff = min(90.0, 2.0 * (2 ** (attempt - 1)))
            wait_s = backoff + random.uniform(0.0, 1.5)
            print(
                f"  API busy ({type(exc).__name__}) for {meeting_id}, "
                f"retry {attempt}/{max_retries} in {wait_s:.1f}s..."
            )
            time.sleep(wait_s)

    raise RuntimeError("Unexpected retry loop exit in call_gemini_bridge")


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def collect_existing_topics(tree: dict[str, Any]) -> list[str]:
    """Collect all known topic keywords from existing L1 memory objects."""
    topics: set[str] = set()
    for meeting in tree.get("meetings", []):
        for obj in meeting.get("memory_objects", []):
            for topic in obj.get("related_topics", []):
                topics.add(topic)
    return sorted(topics)


def normalize_memory_objects(
    raw_objects: list[dict[str, Any]],
    meeting_id: str,
    start_seq: int = 1,
) -> list[dict[str, Any]]:
    """Validate, normalise and assign sequential IDs to memory objects."""
    normalized: list[dict[str, Any]] = []
    seq = start_seq
    for obj in raw_objects:
        obj_type = str(obj.get("type", "")).lower()
        if obj_type not in MEMORY_OBJ_TYPES:
            obj_type = "decision"

        content = str(obj.get("content", "")).strip()
        if not content:
            continue
        if obj_type == "todo" and not content.startswith(TODO_PREFIXES):
            content = f"待辦：{content}"

        evidence = str(obj.get("evidence", "")).strip()

        related_topics: list[str] = []
        raw_topics = obj.get("related_topics", [])
        if isinstance(raw_topics, list):
            for t in raw_topics:
                t_str = str(t).strip()
                if t_str:
                    related_topics.append(t_str)

        importance = calibrate_l1_importance(
            obj_type,
            obj.get("importance", 0.5),
            content=content,
            evidence=evidence,
            related_topics=related_topics,
        )
        if importance < MIN_IMPORTANCE_THRESHOLD:
            continue

        normalized.append(
            {
                "obj_id": f"L1-{meeting_id}-{seq:03d}",
                "type": obj_type,
                "content": content,
                "importance": importance,
                "evidence": evidence,
                "related_topics": related_topics,
                "related_obj_ids": [],
            }
        )
        seq += 1
    return normalized


# ---------------------------------------------------------------------------
# Tree insertion
# ---------------------------------------------------------------------------

def insert_meeting_into_tree(
    tree: dict[str, Any],
    meeting_id: str,
    source_file: str,
    timestamp: str,
    memory_objects: list[dict[str, Any]],
    meeting_date: str = "",
) -> dict[str, Any]:
    """Insert or update an L1 meeting node in the tree."""
    meetings: list[dict[str, Any]] = tree.get("meetings", [])

    existing_idx: int | None = None
    for i, m in enumerate(meetings):
        if m.get("meeting_id") == meeting_id:
            existing_idx = i
            break

    meeting_node: dict[str, Any] = {
        "meeting_id": meeting_id,
        "timestamp": timestamp,  # buildtime
        "meeting_date": meeting_date,  # real meeting date
        "source_file": source_file,
        "phase_id": "",
        "memory_objects": memory_objects,
    }

    if existing_idx is not None:
        meeting_node["phase_id"] = meetings[existing_idx].get("phase_id", "")
        if not meeting_date:
            meeting_node["meeting_date"] = meetings[existing_idx].get("meeting_date", "")
        meetings[existing_idx] = meeting_node
    else:
        meetings.append(meeting_node)

    meetings.sort(key=lambda m: m.get("meeting_id", ""))
    tree["meetings"] = meetings
    tree["tree_version"] = int(tree.get("tree_version", 0) or 0) + 1
    tree["last_updated_utc"] = utc_now_iso()
    return tree


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bridge: extract L1 memory objects from a meeting transcript."
    )
    parser.add_argument(
        "--transcript", required=True, help="Path to meeting transcript file."
    )
    parser.add_argument(
        "--tree",
        default="long_term/tree.json",
        help="Path to temporal memory tree JSON.",
    )
    parser.add_argument(
        "--snapshot-dir",
        default="long_term/snapshots",
        help="Directory for versioned tree snapshots.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("GEMINI_MODEL", DEFAULT_MODEL_NAME),
        help=f"Gemini model name (default: {DEFAULT_MODEL_NAME}).",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "incremental"],
        default="full",
        help="Extraction mode: full keeps the existing full-transcript bridge; incremental uses Gemini function calling.",
    )
    parser.add_argument(
        "--incremental-db",
        default="long_term/incremental_bridge.db",
        help="SQLite working DB for --mode incremental.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=40,
        help="Approximate transcript lines per forward_scan read in --mode incremental.",
    )
    parser.add_argument(
        "--max-tool-rounds",
        type=int,
        default=0,
        help=(
            "Maximum Gemini tool-calling rounds in --mode incremental. "
            "Use 0 for an automatic transcript-size-based limit."
        ),
    )
    parser.add_argument(
        "--timestamp",
        default="",
        help="Meeting timestamp (ISO 8601). Auto-generated if empty.",
    )
    parser.add_argument(
        "--meeting-date",
        default="",
        help="實際會議日期（YYYY-MM-DD），用於 recency 計算。若不傳則留空。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results without writing files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    transcript_path = Path(args.transcript).resolve()
    tree_path = Path(args.tree).resolve()
    snapshot_dir = Path(args.snapshot_dir).resolve()

    if not transcript_path.exists():
        raise RuntimeError(f"Transcript not found: {transcript_path}")

    meeting_id = transcript_path.stem
    source_file = str(transcript_path)
    transcript = transcript_path.read_text(encoding="utf-8")
    timestamp = args.timestamp or utc_now_iso()
    meeting_date = args.meeting_date

    tree = load_tree(tree_path)
    api_keys = load_api_keys()
    existing_topics = collect_existing_topics(tree)

    if args.mode == "incremental":
        # New mode plugs into the existing pipeline here: Gemini tool-calling
        # produces raw L1 candidates, then the current normalizer/tree writer run.
        from gemini_incremental_extractor import extract_incremental_l1_objects

        incremental_result = extract_incremental_l1_objects(
            model_name=args.model,
            api_key=api_keys,
            transcript=transcript,
            transcript_id=meeting_id,
            db_path=Path(args.incremental_db).resolve(),
            existing_topics=existing_topics,
            chunk_size=args.chunk_size,
            max_tool_rounds=args.max_tool_rounds,
        )
        raw_objects = incremental_result.raw_objects
    else:
        llm_output = call_gemini_bridge(
            model_name=args.model,
            api_key=api_keys,
            transcript=transcript,
            meeting_id=meeting_id,
            existing_topics=existing_topics,
        )
        raw_objects = llm_output.get("memory_objects", [])

    memory_objects = normalize_memory_objects(raw_objects, meeting_id)

    insert_meeting_into_tree(
        tree=tree,
        meeting_id=meeting_id,
        source_file=source_file,
        timestamp=timestamp,
        memory_objects=memory_objects,
        meeting_date=meeting_date,
    )

    if args.dry_run:
        print_json_safe(tree)
        return

    save_json(tree_path, tree)
    snapshot_name = (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_bridge_{meeting_id}.json"
    )
    save_json(snapshot_dir / snapshot_name, tree)

    if args.mode == "incremental":
        print(
            f"Incremental bridge: inserted {len(memory_objects)} memory objects for {meeting_id}"
        )
        print(f"Incremental DB: {Path(args.incremental_db).resolve()}")
    else:
        print(f"Bridge: inserted {len(memory_objects)} memory objects for {meeting_id}")
    print(f"Tree version: {tree['tree_version']}")
    print(f"Tree saved: {tree_path}")


if __name__ == "__main__":
    main()
