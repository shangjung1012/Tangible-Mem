"""Bridge: Extract L1 memory objects from a meeting transcript and insert into
the temporal memory tree."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from google import genai

from io_utils import load_env, load_tree, print_json_safe, save_json, utc_now_iso
from schema import BRIDGE_RESPONSE_SCHEMA, DEFAULT_MODEL_NAME, MEMORY_OBJ_TYPES


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
任務：從單次會議逐字稿中，擷取所有重要的記憶物件，分類為 decision / todo / method_change / result。

規則：
1) 回傳 JSON only，不要有任何額外文字。
2) 每個記憶物件必須有 type、content、importance、evidence、related_topics。
3) type 含義：
   - decision：會議中做出的決策或結論
   - todo：被指派或提及的待辦事項
   - method_change：方法論、演算法、流程的變更
   - result：實驗結果、發現、觀察報告
4) importance 評分標準：
   - 0.8~1.0：影響整個研究方向的重大決策或方法變更
   - 0.5~0.7：重要的待辦或中等重要的技術決策
   - 0.3~0.4：一般性的討論結論
   - 0.1~0.2：瑣碎的行政事項
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
    api_key: str,
    transcript: str,
    meeting_id: str,
    existing_topics: list[str],
) -> dict[str, Any]:
    client = genai.Client(api_key=api_key)
    prompt = build_bridge_prompt(transcript, meeting_id, existing_topics)
    config = {
        "temperature": 0.15,
        "response_mime_type": "application/json",
        "response_json_schema": BRIDGE_RESPONSE_SCHEMA,
    }
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=config,
    )
    return extract_json(response.text or "")


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

        importance = obj.get("importance", 0.5)
        try:
            importance = float(importance)
        except (TypeError, ValueError):
            importance = 0.5
        importance = max(0.0, min(1.0, round(importance, 2)))

        content = str(obj.get("content", "")).strip()
        if not content:
            continue

        evidence = str(obj.get("evidence", "")).strip()

        related_topics: list[str] = []
        raw_topics = obj.get("related_topics", [])
        if isinstance(raw_topics, list):
            for t in raw_topics:
                t_str = str(t).strip()
                if t_str:
                    related_topics.append(t_str)

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
        "timestamp": timestamp,
        "source_file": source_file,
        "phase_id": "",
        "memory_objects": memory_objects,
    }

    if existing_idx is not None:
        meeting_node["phase_id"] = meetings[existing_idx].get("phase_id", "")
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
        "--timestamp",
        default="",
        help="Meeting timestamp (ISO 8601). Auto-generated if empty.",
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

    tree = load_tree(tree_path)
    api_key = load_env()
    existing_topics = collect_existing_topics(tree)

    llm_output = call_gemini_bridge(
        model_name=args.model,
        api_key=api_key,
        transcript=transcript,
        meeting_id=meeting_id,
        existing_topics=existing_topics,
    )

    raw_objects = llm_output.get("memory_objects", [])
    memory_objects = normalize_memory_objects(raw_objects, meeting_id)

    insert_meeting_into_tree(tree, meeting_id, source_file, timestamp, memory_objects)

    if args.dry_run:
        print_json_safe(tree)
        return

    save_json(tree_path, tree)
    snapshot_name = (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_bridge_{meeting_id}.json"
    )
    save_json(snapshot_dir / snapshot_name, tree)

    print(f"Bridge: inserted {len(memory_objects)} memory objects for {meeting_id}")
    print(f"Tree version: {tree['tree_version']}")
    print(f"Tree saved: {tree_path}")


if __name__ == "__main__":
    main()
