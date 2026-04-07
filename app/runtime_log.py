from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "record" / "runtime_logs"


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _safe_preview(text: str, max_chars: int = 320) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...(truncated)"


def _append_event(event: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"runtime_{datetime.now().strftime('%Y%m%d')}.jsonl"
    with open(log_path, "a+", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def log_user_question(question: str) -> None:
    _append_event(
        {
            "time_utc": _utc_now_iso(),
            "event": "user_question",
            "question": question,
        }
    )


def log_assistant_answer(answer: str) -> None:
    _append_event(
        {
            "time_utc": _utc_now_iso(),
            "event": "assistant_answer",
            "answer_preview": _safe_preview(answer, max_chars=500),
        }
    )


def log_tool_result(tool_name: str, query: str, context: str) -> None:
    preview = _safe_preview(context, max_chars=500)
    print(
        f"\n[ToolCall] {tool_name} | query='{_safe_preview(query, 120)}' "
        f"| result_preview='{_safe_preview(context, 120)}'"
    )
    _append_event(
        {
            "time_utc": _utc_now_iso(),
            "event": "tool_result",
            "tool": tool_name,
            "query": query,
            "result_chars": len(context or ""),
            "result_preview": preview,
        }
    )

