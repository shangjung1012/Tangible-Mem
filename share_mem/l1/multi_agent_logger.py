"""Structured artifact logging for multi-agent long-term extraction."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .io_utils import utc_now_iso
from .multi_agent_state import to_plain


class ResearchLogger:
    def __init__(self, root_dir: Path, run_id: str) -> None:
        self.run_dir = root_dir / run_id
        self.prompts_dir = self.run_dir / "prompts"
        self.responses_dir = self.run_dir / "responses"
        self.api_calls_dir = self.run_dir / "api_calls"
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        self.responses_dir.mkdir(parents=True, exist_ok=True)
        self.api_calls_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_dir / "graph_events.jsonl"
        self.api_calls_jsonl_path = self.api_calls_dir / "api_calls.jsonl"
        self._api_call_seq = self._existing_api_call_seq()

    def _existing_api_call_seq(self) -> int:
        max_seq = 0
        for path in self.api_calls_dir.glob("*.json"):
            prefix = path.name.split("_", 1)[0]
            if prefix.isdigit():
                max_seq = max(max_seq, int(prefix))
        return max_seq

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

    def write_api_call(
        self,
        *,
        stage: str,
        attempt: int,
        model: str,
        config: dict[str, Any],
        schema: dict[str, Any],
        prompt: str,
        raw_response: str,
        parsed_json: Any | None,
        latency_sec: float,
        success: bool,
        error: dict[str, Any] | None,
        usage_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._api_call_seq += 1
        safe_stage = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(stage)).strip("_")
        payload = {
            "sequence": self._api_call_seq,
            "timestamp_utc": utc_now_iso(),
            "stage": stage,
            "attempt": attempt,
            "model": model,
            "config": config,
            "schema": to_plain(schema),
            "prompt": prompt,
            "raw_response": raw_response or "",
            "parsed_json": to_plain(parsed_json),
            "latency_sec": latency_sec,
            "success": bool(success),
            "error": error,
            "usage_metadata": to_plain(usage_metadata or {}),
        }
        path = self.api_calls_dir / (
            f"{self._api_call_seq:03d}_{safe_stage or 'stage'}_attempt{attempt}.json"
        )
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with self.api_calls_jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return payload
