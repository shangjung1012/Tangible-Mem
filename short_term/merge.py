from __future__ import annotations

import json
import math
import multiprocessing as mp
import os
import re
import signal
import threading
from copy import deepcopy
from queue import Empty, Queue
from pathlib import Path
from typing import Any, Callable

from share_mem.l1.gemini_clients import create_gemini_client
from share_mem.l1.io_utils import load_api_keys

from .io_utils import dedupe_keep_order, normalize_str, normalize_str_list
from .schema import DEFAULT_MODEL_NAME, MERGE_DECISION_SCHEMA

TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]+", re.IGNORECASE)
MergeDecider = Callable[[dict[str, Any], list[dict[str, Any]], dict[str, Any]], dict[str, Any]]
TRANSIENT_MERGE_ERROR_MARKERS = (
    "429",
    "499",
    "500",
    "502",
    "503",
    "504",
    "CANCELLED",
    "DEADLINE_EXCEEDED",
    "RESOURCE_EXHAUSTED",
    "UNAVAILABLE",
)


def _tokens(text: str) -> set[str]:
    output: set[str] = set()
    for match in TOKEN_RE.findall(str(text).lower()):
        if len(match) >= 2 or re.fullmatch(r"[\u4e00-\u9fff]+", match):
            output.add(match)
    return output


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _is_transient_merge_error(exc: BaseException) -> bool:
    message = str(exc).upper()
    return any(marker in message for marker in TRANSIENT_MERGE_ERROR_MARKERS)


def _topic_set(row: dict[str, Any]) -> set[str]:
    return {topic.lower() for topic in normalize_str_list(row.get("related_topics"))}


def _unit_text(unit: dict[str, Any]) -> str:
    return " ".join(
        [
            normalize_str(unit.get("title")),
            normalize_str(unit.get("summary")),
            " ".join(normalize_str_list(unit.get("related_topics"))),
        ]
    )


def _obj_text(source_obj: dict[str, Any]) -> str:
    return " ".join(
        [
            normalize_str(source_obj.get("content")),
            normalize_str(source_obj.get("evidence")),
            " ".join(normalize_str_list(source_obj.get("related_topics"))),
        ]
    )


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def select_candidate_units(
    source_obj: dict[str, Any],
    memory: dict[str, Any],
    *,
    max_candidates: int = 5,
) -> list[dict[str, Any]]:
    """Return bounded candidate units for a new L1 object."""
    source_obj_id = normalize_str(source_obj.get("obj_id"))
    source_topics = _topic_set(source_obj)
    source_tokens = _tokens(_obj_text(source_obj))
    source_type = normalize_str(source_obj.get("type"))
    scored: list[tuple[float, dict[str, Any]]] = []

    for unit in memory.get("units", []):
        if not isinstance(unit, dict):
            continue
        score = 0.0
        unit_sources = set(normalize_str_list(unit.get("source_obj_ids")))
        if source_obj_id and source_obj_id in unit_sources:
            score += 3.0
        unit_topics = _topic_set(unit)
        topic_score = _jaccard(source_topics, unit_topics)
        score += topic_score * 2.0
        token_score = _jaccard(source_tokens, _tokens(_unit_text(unit)))
        score += token_score
        unit_types = set(normalize_str_list(unit.get("types")))
        if source_type and source_type in unit_types:
            score += 0.25
        if score > 0:
            candidate = deepcopy(unit)
            candidate["_candidate_score"] = round(score, 4)
            scored.append((score, candidate))

    scored.sort(key=lambda item: (-item[0], normalize_str(item[1].get("unit_id"))))
    return [candidate for _, candidate in scored[:max_candidates]]


def next_unit_id(units: list[dict[str, Any]]) -> str:
    max_number = 0
    for unit in units:
        unit_id = normalize_str(unit.get("unit_id"))
        match = re.fullmatch(r"S(\d+)", unit_id)
        if match:
            max_number = max(max_number, int(match.group(1)))
    return f"S{max_number + 1:03d}"


def _meeting_index(memory: dict[str, Any], meeting_id: str) -> int:
    history = normalize_str_list(memory.get("meeting_history_ids"))
    if meeting_id not in history:
        history.append(meeting_id)
    return history.index(meeting_id)


def _normalize_decision(decision: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(decision, dict):
        raise ValueError("merge decision must be a JSON object")
    action = normalize_str(decision.get("action"))
    if action not in {"merge_existing", "create_new"}:
        raise ValueError(f"unsupported merge action: {action}")
    title = normalize_str(decision.get("title"))
    summary = normalize_str(decision.get("summary"))
    if not title:
        raise ValueError("merge decision must include title")
    if not summary:
        raise ValueError("merge decision must include summary")
    return {
        "action": action,
        "unit_id": normalize_str(decision.get("unit_id")),
        "title": title,
        "summary": summary,
        "related_topics": normalize_str_list(decision.get("related_topics")),
        "rationale": normalize_str(decision.get("rationale")),
    }


def apply_merge_decision(
    *,
    memory: dict[str, Any],
    source_obj: dict[str, Any],
    meeting: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    normalized = _normalize_decision(decision)
    units = memory.setdefault("units", [])
    meeting_id = normalize_str(meeting.get("meeting_id"))
    source_obj_id = normalize_str(source_obj.get("obj_id"))
    if not source_obj_id:
        raise ValueError("source L1 object is missing obj_id")
    meeting_index = _meeting_index(memory, meeting_id)
    obj_type = normalize_str(source_obj.get("type"))
    source_topics = normalize_str_list(source_obj.get("related_topics"))
    source_ids = [source_obj_id]

    if normalized["action"] == "merge_existing":
        unit_id = normalized["unit_id"]
        unit = next(
            (candidate for candidate in units if normalize_str(candidate.get("unit_id")) == unit_id),
            None,
        )
        if unit is None:
            raise ValueError(f"unknown unit_id for merge_existing: {unit_id}")
        unit["title"] = normalized["title"]
        unit["summary"] = normalized["summary"]
        unit["types"] = dedupe_keep_order(normalize_str_list(unit.get("types")) + [obj_type])
        unit["related_topics"] = dedupe_keep_order(
            normalize_str_list(unit.get("related_topics"))
            + normalized["related_topics"]
            + source_topics
        )
        unit["source_obj_ids"] = dedupe_keep_order(
            normalize_str_list(unit.get("source_obj_ids")) + source_ids
        )
        unit["last_updated_meeting_id"] = meeting_id
        unit["last_seen_meeting_index"] = meeting_index
        unit["missed_meeting_count"] = 0
        history = unit.get("update_history")
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "meeting_id": meeting_id,
                "source_obj_ids": source_ids,
                "change": normalized["rationale"] or "merged related L1 object",
            }
        )
        unit["update_history"] = history
        return unit

    unit = {
        "unit_id": next_unit_id(units),
        "title": normalized["title"],
        "summary": normalized["summary"],
        "types": dedupe_keep_order([obj_type]),
        "related_topics": dedupe_keep_order(normalized["related_topics"] + source_topics),
        "source_obj_ids": source_ids,
        "created_meeting_id": meeting_id,
        "last_updated_meeting_id": meeting_id,
        "last_seen_meeting_index": meeting_index,
        "missed_meeting_count": 0,
        "update_history": [
            {
                "meeting_id": meeting_id,
                "source_obj_ids": source_ids,
                "change": normalized["rationale"] or "created from L1 object",
            }
        ],
    }
    units.append(unit)
    return unit


def _extract_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise RuntimeError("Gemini returned an empty merge decision")
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("Gemini merge decision did not contain JSON")
    parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise RuntimeError("Gemini merge decision must be an object")
    return parsed


def _run_func_and_report(
    func: Callable[[], dict[str, Any]],
    queue: Any,
) -> None:
    try:
        queue.put(("ok", func()))
    except BaseException as exc:  # pragma: no cover - exercised through parent
        queue.put(("error", exc.__class__.__name__, str(exc)))


def _read_worker_report(queue: Any, operation_name: str) -> dict[str, Any]:
    try:
        status, *payload = queue.get_nowait()
    except Empty as exc:
        raise RuntimeError(
            f"{operation_name} worker exited without returning a result"
        ) from exc
    if status == "ok":
        result = payload[0]
        if not isinstance(result, dict):
            raise RuntimeError(f"{operation_name} returned a non-object result")
        return result
    exc_type = payload[0] if payload else "Exception"
    message = payload[1] if len(payload) > 1 else ""
    raise RuntimeError(f"{operation_name} failed in worker ({exc_type}): {message}")


def build_merge_prompt(
    *,
    source_obj: dict[str, Any],
    candidates: list[dict[str, Any]],
    meeting: dict[str, Any],
) -> str:
    compact_candidates = [
        {
            "unit_id": unit.get("unit_id", ""),
            "title": unit.get("title", ""),
            "summary": unit.get("summary", ""),
            "types": unit.get("types", []),
            "related_topics": unit.get("related_topics", []),
            "source_obj_ids": unit.get("source_obj_ids", []),
            "candidate_score": unit.get("_candidate_score", 0.0),
        }
        for unit in candidates
    ]
    return f"""
You are updating short-term memory from share_mem L1 objects.

Decide whether the new L1 object updates one candidate short-term topic unit or
must create a new topic unit.

Rules:
1) Return JSON only.
2) action must be merge_existing or create_new.
3) Use merge_existing only when the L1 object is the same ongoing short-term topic.
4) If action=merge_existing, unit_id must be one of the candidate unit IDs.
5) Do not invent source object IDs.
6) Keep title short and summary focused on the current state after this update.

Meeting:
{json.dumps({"meeting_id": meeting.get("meeting_id", ""), "meeting_date": meeting.get("meeting_date", "")}, ensure_ascii=False)}

New L1 object:
{json.dumps(source_obj, ensure_ascii=False)}

Candidate short-term units:
{json.dumps(compact_candidates, ensure_ascii=False)}
""".strip()


def run_with_timeout(
    func: Callable[[], dict[str, Any]],
    *,
    timeout_s: float,
    operation_name: str,
) -> dict[str, Any]:
    if timeout_s <= 0:
        return func()
    if hasattr(os, "fork"):
        ctx = mp.get_context("fork")
        queue = ctx.Queue(maxsize=1)
        process = ctx.Process(target=_run_func_and_report, args=(func, queue))
        process.start()
        process.join(timeout_s)
        if process.is_alive():
            process.terminate()
            process.join(1)
            if process.is_alive():
                process.kill()
                process.join()
            raise TimeoutError(f"{operation_name} timed out after {timeout_s:g}s")
        return _read_worker_report(queue, operation_name)

    if not hasattr(signal, "setitimer"):
        queue: Queue[tuple[Any, ...]] = Queue(maxsize=1)
        thread = threading.Thread(
            target=_run_func_and_report,
            args=(func, queue),
            daemon=True,
        )
        thread.start()
        thread.join(timeout_s)
        if thread.is_alive():
            raise TimeoutError(f"{operation_name} timed out after {timeout_s:g}s")
        return _read_worker_report(queue, operation_name)

    def _handle_timeout(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"{operation_name} timed out after {timeout_s:g}s")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_s)
    try:
        return func()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


class GeminiMergeDecider:
    def __init__(
        self,
        *,
        model_name: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.model_name = model_name or os.getenv("GEMINI_MODEL", DEFAULT_MODEL_NAME)
        self.timeout_s = (
            float(os.getenv("SHORT_TERM_MERGE_TIMEOUT_S", "60"))
            if timeout_s is None
            else timeout_s
        )
        if self.timeout_s > 0 and not os.getenv("GEMINI_HTTP_TIMEOUT_S"):
            os.environ["GEMINI_HTTP_TIMEOUT_S"] = str(max(1, math.ceil(self.timeout_s)))
        self.max_retries = max(0, _env_int("SHORT_TERM_MERGE_RETRIES", 2))
        self.client = create_gemini_client(load_api_keys())

    def __call__(
        self,
        source_obj: dict[str, Any],
        candidates: list[dict[str, Any]],
        meeting: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = build_merge_prompt(
            source_obj=source_obj,
            candidates=candidates,
            meeting=meeting,
        )
        for attempt in range(self.max_retries + 1):
            try:
                return run_with_timeout(
                    lambda: _extract_json(
                        (
                            self.client.models.generate_content(
                                model=self.model_name,
                                contents=prompt,
                                config={
                                    "temperature": 0.1,
                                    "response_mime_type": "application/json",
                                    "response_json_schema": MERGE_DECISION_SCHEMA,
                                },
                            ).text
                            or ""
                        )
                    ),
                    timeout_s=self.timeout_s,
                    operation_name="short-term Gemini merge decision",
                )
            except RuntimeError as exc:
                if attempt >= self.max_retries or not _is_transient_merge_error(exc):
                    raise
        raise RuntimeError("short-term Gemini merge decision failed")
