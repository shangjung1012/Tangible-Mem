"""Structured artifact logging for multi-agent long-term extraction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from io_utils import utc_now_iso
from multi_agent_state import to_plain


class ResearchLogger:
    def __init__(self, root_dir: Path, run_id: str) -> None:
        self.run_dir = root_dir / run_id
        self.prompts_dir = self.run_dir / "prompts"
        self.responses_dir = self.run_dir / "responses"
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        self.responses_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_dir / "graph_events.jsonl"

    def write_json(self, filename: str, data: Any) -> None:
        path = self.run_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(to_plain(data), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def append_event(self, stage: str, payload: dict[str, Any] | None = None) -> None:
        event = {
            "timestamp_utc": utc_now_iso(),
            "stage": stage,
            "payload": payload or {},
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def write_prompt(self, stage: str, prompt: str) -> None:
        (self.prompts_dir / f"{stage}.txt").write_text(prompt, encoding="utf-8")

    def write_response(self, stage: str, raw_text: str) -> None:
        (self.responses_dir / f"{stage}.txt").write_text(raw_text or "", encoding="utf-8")
