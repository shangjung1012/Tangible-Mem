"""Bridge: Extract L1 memory objects from a meeting transcript and insert into
the temporal memory tree."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from gemini_clients import create_gemini_client
from importance import (
    IMPORTANCE_SCALE,
    MIN_IMPORTANCE_THRESHOLD,
    apply_linked_issue_importance_bonus,
    calibrate_l1_importance,
    is_low_value_text,
    linked_issue_importance_bonus,
    normalize_importance_score,
)
from io_utils import load_api_keys, load_tree, print_json_safe, save_json, utc_now_iso
from schema import BRIDGE_RESPONSE_SCHEMA, DEFAULT_MODEL_NAME, MEMORY_OBJ_TYPES

TODO_PREFIXES = ("需要", "待辦", "應", "計劃", "必須")
_CANDIDATE_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
_SPECULATIVE_OBJ_TYPES = {"argument", "open_question"}
_CHECKLIST_MARKERS = (
    "needs to include",
    "should include",
    "include:",
    "includes:",
    "包含：",
    "需要包含",
    "應包含",
)
_INCREMENTAL_TYPE_IMPORTANCE_CAPS = {
    "argument": 0.8,
    "open_question": 0.85,
    "result": 0.9,
}
_INCREMENTAL_FINAL_TYPE_IMPORTANCE_CAPS = {
    "decision": 0.92,
    "method_change": 0.88,
    "result": 0.88,
    "todo": 0.65,
    "open_question": 0.80,
    "argument": 0.76,
}


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


def _candidate_tokens(text: str) -> list[str]:
    return [token.lower() for token in _CANDIDATE_TOKEN_RE.findall(str(text or ""))]


def _candidate_signature(obj_type: str, content: str) -> tuple[str, tuple[str, ...]]:
    tokens = _candidate_tokens(content)
    return str(obj_type or "").lower(), tuple(tokens[:10])


def _jaccard_overlap(left: list[str], right: list[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _merge_topics(left: list[str], right: list[str]) -> list[str]:
    merged: list[str] = []
    for topic in [*left, *right]:
        clean = str(topic).strip()
        if clean and clean not in merged:
            merged.append(clean)
    return merged


def _token_overlap_ratio(left: list[str], right: list[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / min(len(left_set), len(right_set))


def _is_checklist_like(content: str) -> bool:
    text = str(content or "")
    lowered = text.lower()
    comma_count = text.count(",") + text.count("，") + text.count(";") + text.count("；")
    token_count = len(_candidate_tokens(text))
    return (
        any(marker in lowered for marker in _CHECKLIST_MARKERS)
        or comma_count >= 8
        or token_count >= 55
    )


def _choose_more_durable_candidate(
    current: dict[str, Any],
    existing: dict[str, Any],
) -> dict[str, Any]:
    current_content = str(current.get("content") or "")
    existing_content = str(existing.get("content") or "")
    current_checklist = _is_checklist_like(current_content)
    existing_checklist = _is_checklist_like(existing_content)

    if current_checklist != existing_checklist:
        return current if not current_checklist else existing

    current_tokens = len(_candidate_tokens(current_content))
    existing_tokens = len(_candidate_tokens(existing_content))
    if current_tokens != existing_tokens:
        return current if current_tokens < existing_tokens else existing

    current_score = normalize_importance_score(current.get("importance", 0.0), fallback=0.0)
    existing_score = normalize_importance_score(existing.get("importance", 0.0), fallback=0.0)
    return current if current_score >= existing_score else existing


def _merge_candidate_rows(
    preferred: dict[str, Any],
    other: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(preferred)
    preferred_evidence = str(preferred.get("evidence") or "")
    other_evidence = str(other.get("evidence") or "")
    if len(other_evidence) > len(preferred_evidence):
        merged["evidence"] = other_evidence
    merged["related_topics"] = _merge_topics(
        preferred.get("related_topics", []),
        other.get("related_topics", []),
    )
    merged["importance"] = max(
        normalize_importance_score(preferred.get("importance", 0.0), fallback=0.0),
        normalize_importance_score(other.get("importance", 0.0), fallback=0.0),
    )
    merged_review = dict(merged.get("_candidate_review", {}))
    other_adjustments = list(other.get("_candidate_review", {}).get("adjustments", []))
    merged_adjustments = list(merged_review.get("adjustments", []))
    merged_adjustments.extend(
        adjustment
        for adjustment in other_adjustments
        if adjustment not in merged_adjustments
    )
    if "merged_same_issue:+0.00" not in merged_adjustments:
        merged_adjustments.append("merged_same_issue:+0.00")
    merged_review["adjustments"] = merged_adjustments
    merged["_candidate_review"] = merged_review
    return merged


def _find_issue_group_duplicate_index(
    reviewed: list[dict[str, Any]],
    row: dict[str, Any],
    *,
    issue_id: str,
    obj_type: str,
    content_tokens: list[str],
) -> int | None:
    if not issue_id or not content_tokens:
        return None
    checklist_like = _is_checklist_like(row.get("content", ""))
    for index, existing in enumerate(reviewed):
        existing_issue_id = str(existing.get("_issue_id") or existing.get("issue_id") or "").strip()
        existing_type = str(existing.get("type") or "").lower()
        if existing_issue_id != issue_id or existing_type != obj_type:
            continue
        existing_tokens = _candidate_tokens(existing.get("content", ""))
        overlap = _token_overlap_ratio(content_tokens, existing_tokens)
        if overlap >= 0.55:
            return index
        if checklist_like and overlap >= 0.2:
            return index
    return None


def review_incremental_candidates(
    raw_objects: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Lightweight incremental-only candidate review before final normalization.

    This pass is intentionally bounded and deterministic:
    - dedupe near-identical raw objects
    - penalize unsupported speculative objects
    - lightly reward/punish consistency with a linked issue
    """
    issue_by_id = {
        str(issue.get("issue_id") or ""): issue
        for issue in issues
        if str(issue.get("issue_id") or "").strip()
    }
    reviewed: list[dict[str, Any]] = []
    signature_index: dict[tuple[str, tuple[str, ...]], int] = {}
    stats = {
        "input": len(raw_objects),
        "kept": 0,
        "dropped_duplicate": 0,
        "dropped_weak": 0,
    }

    for raw_object in raw_objects:
        row = dict(raw_object)
        obj_type = str(row.get("type") or "decision").lower()
        content = str(row.get("content") or "").strip()
        evidence = str(row.get("evidence") or "").strip()
        related_topics = [
            str(topic).strip()
            for topic in row.get("related_topics", [])
            if str(topic).strip()
        ] if isinstance(row.get("related_topics", []), list) else []
        issue_id = str(row.get("_issue_id") or row.get("issue_id") or "").strip()
        linked_issue = issue_by_id.get(issue_id)

        if not content:
            stats["dropped_weak"] += 1
            continue

        base_importance = normalize_importance_score(row.get("importance", 0.5))
        reviewed_importance = base_importance
        adjustments: list[str] = []

        evidence_tokens = _candidate_tokens(evidence)
        content_tokens = _candidate_tokens(content)
        topic_tokens = _candidate_tokens(" ".join(related_topics))
        object_tokens = [*content_tokens, *evidence_tokens, *topic_tokens]
        checklist_like = _is_checklist_like(content)

        if not evidence_tokens:
            reviewed_importance = normalize_importance_score(reviewed_importance - 0.06)
            adjustments.append("missing_evidence:-0.06")
        elif len(evidence_tokens) < 4:
            reviewed_importance = normalize_importance_score(reviewed_importance - 0.03)
            adjustments.append("short_evidence:-0.03")

        if checklist_like:
            reviewed_importance = normalize_importance_score(reviewed_importance - 0.08)
            adjustments.append("checklist_fragment:-0.08")

        issue_overlap = 0.0
        issue_text = ""
        if linked_issue is not None:
            issue_text = f"{linked_issue.get('title', '')}\n{linked_issue.get('summary', '')}"
            issue_tokens = _candidate_tokens(
                f"{linked_issue.get('title', '')} {linked_issue.get('summary', '')}"
            )
            issue_overlap = _jaccard_overlap(object_tokens, issue_tokens)
            if issue_overlap >= 0.12:
                reviewed_importance = normalize_importance_score(reviewed_importance + 0.03)
                adjustments.append("issue_aligned:+0.03")
            elif issue_overlap < 0.04:
                reviewed_importance = normalize_importance_score(reviewed_importance - 0.04)
                adjustments.append("issue_misaligned:-0.04")
        elif obj_type in _SPECULATIVE_OBJ_TYPES:
            reviewed_importance = normalize_importance_score(reviewed_importance - 0.05)
            adjustments.append("unlinked_speculative:-0.05")

        low_value_object = is_low_value_text(f"{content}\n{evidence}")
        low_value_issue = bool(issue_text) and is_low_value_text(issue_text)
        if low_value_object:
            reviewed_importance = normalize_importance_score(reviewed_importance - 0.18)
            adjustments.append("low_value_context:-0.18")
        if low_value_issue:
            reviewed_importance = normalize_importance_score(reviewed_importance - 0.10)
            adjustments.append("low_value_issue:-0.10")

        if (
            linked_issue is None
            and obj_type in _SPECULATIVE_OBJ_TYPES
            and not evidence_tokens
            and base_importance < 0.6
        ):
            stats["dropped_weak"] += 1
            continue
        if (
            (low_value_object or low_value_issue)
            and obj_type in {"result", "argument", "open_question", "todo"}
            and reviewed_importance < 0.60
        ):
            stats["dropped_weak"] += 1
            continue

        type_cap = _INCREMENTAL_TYPE_IMPORTANCE_CAPS.get(obj_type)
        if type_cap is not None and reviewed_importance > type_cap:
            reviewed_importance = normalize_importance_score(type_cap)
            adjustments.append(f"type_cap:{type_cap:.2f}")

        row["importance"] = reviewed_importance
        row["_candidate_review"] = {
            "base_importance": base_importance,
            "reviewed_importance": reviewed_importance,
            "issue_overlap": round(issue_overlap, 3),
            "adjustments": adjustments,
        }
        row["related_topics"] = related_topics

        signature = _candidate_signature(obj_type, content)
        if signature[1] and signature in signature_index:
            kept_idx = signature_index[signature]
            existing = reviewed[kept_idx]
            existing_score = normalize_importance_score(existing.get("importance", 0.0), fallback=0.0)
            current_score = normalize_importance_score(row.get("importance", 0.0), fallback=0.0)
            if current_score > existing_score:
                row["related_topics"] = _merge_topics(
                    related_topics,
                    existing.get("related_topics", []),
                )
                if len(evidence) < len(str(existing.get("evidence") or "")):
                    row["evidence"] = str(existing.get("evidence") or "")
                reviewed[kept_idx] = row
            else:
                existing["related_topics"] = _merge_topics(
                    existing.get("related_topics", []),
                    related_topics,
                )
                if len(evidence) > len(str(existing.get("evidence") or "")):
                    existing["evidence"] = evidence
                existing["importance"] = max(
                    normalize_importance_score(existing.get("importance", 0.0), fallback=0.0),
                    current_score,
                )
            stats["dropped_duplicate"] += 1
            continue

        merge_idx = _find_issue_group_duplicate_index(
            reviewed,
            row,
            issue_id=issue_id,
            obj_type=obj_type,
            content_tokens=content_tokens,
        )
        if merge_idx is not None:
            existing = reviewed[merge_idx]
            preferred = _choose_more_durable_candidate(row, existing)
            other = existing if preferred is row else row
            reviewed[merge_idx] = _merge_candidate_rows(preferred, other)
            stats["dropped_duplicate"] += 1
            continue

        signature_index[signature] = len(reviewed)
        reviewed.append(row)

    stats["kept"] = len(reviewed)
    return reviewed, stats


def propagate_issue_importance_to_raw_objects(
    raw_objects: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply a small bounded bonus from recurring linked issues before normalization.

    This is incremental-only metadata propagation. The final L1 schema is unchanged
    because normalize_memory_objects() ignores the internal _issue_id fields.
    """
    issue_importance_by_id = {
        str(issue.get("issue_id") or ""): issue.get("importance", 0.0)
        for issue in issues
        if str(issue.get("issue_id") or "").strip()
    }
    issue_importance_by_key = {
        str(issue.get("issue_key") or ""): issue.get("importance", 0.0)
        for issue in issues
        if str(issue.get("issue_key") or "").strip()
    }
    adjusted: list[dict[str, Any]] = []
    for raw_object in raw_objects:
        row = dict(raw_object)
        issue_id = str(row.get("_issue_id") or row.get("issue_id") or "").strip()
        issue_importance = issue_importance_by_id.get(issue_id)
        if issue_importance is None:
            issue_importance = issue_importance_by_key.get(issue_id)
        if issue_importance is None:
            adjusted.append(row)
            continue

        bonus = linked_issue_importance_bonus(issue_importance)
        if bonus > 0:
            row["importance"] = apply_linked_issue_importance_bonus(
                row.get("importance", 0.5),
                issue_importance,
            )
        adjusted.append(row)
    return adjusted


def apply_incremental_final_importance_caps(
    memory_objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep incremental final scores readable without touching full-mode behavior."""
    capped: list[dict[str, Any]] = []
    for memory_object in memory_objects:
        row = dict(memory_object)
        obj_type = str(row.get("type") or "").lower()
        type_cap = _INCREMENTAL_FINAL_TYPE_IMPORTANCE_CAPS.get(obj_type)
        if type_cap is not None:
            importance = normalize_importance_score(
                row.get("importance", 0.0),
                fallback=0.0,
            )
            row["importance"] = min(importance, type_cap)
        capped.append(row)
    return capped


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
        reviewed_raw_objects, review_stats = review_incremental_candidates(
            incremental_result.raw_objects,
            incremental_result.issues,
        )
        print(
            (
                f"[incremental] candidate review: kept={review_stats['kept']}/"
                f"{review_stats['input']}, dropped_duplicate={review_stats['dropped_duplicate']}, "
                f"dropped_weak={review_stats['dropped_weak']}"
            ),
            file=sys.stderr,
            flush=True,
        )
        raw_objects = propagate_issue_importance_to_raw_objects(
            reviewed_raw_objects,
            incremental_result.issues,
        )
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
    if args.mode == "incremental":
        memory_objects = apply_incremental_final_importance_caps(memory_objects)

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
