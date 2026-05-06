from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ResearchLogger:
    def __init__(
        self,
        root_dir: Path,
        meeting_id: str,
        *,
        log_level: str = "debug",
        keep_full_prompts: bool = True,
        run_id: str | None = None,
    ) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_id = run_id or f"{timestamp}_{meeting_id}"
        self.root_dir = root_dir
        self.run_dir = root_dir / self.run_id
        self.log_level = log_level if log_level in {"summary", "debug"} else "debug"
        self.keep_full_prompts = keep_full_prompts
        self._counter = 0
        for child in (
            "state_snapshots",
            "prompts",
            "responses",
            "candidates",
            "tool_calls",
        ):
            (self.run_dir / child).mkdir(parents=True, exist_ok=True)

    def write_run_meta(self, data: dict[str, Any]) -> None:
        payload = {"run_id": self.run_id, **data}
        self._write_json(self.run_dir / "run_meta.json", payload)

    def graph_event(
        self,
        *,
        node: str,
        event: str,
        status: str = "ok",
        summary: dict[str, Any] | None = None,
        line_range: str = "",
        duration_seconds: float | None = None,
    ) -> None:
        payload = {
            "run_id": self.run_id,
            "node": node,
            "event": event,
            "timestamp": _utc_like_now(),
            "status": status,
            "line_range": line_range,
            "duration_seconds": duration_seconds,
            "summary": summary or {},
        }
        path = self.run_dir / "graph_events.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def state_snapshot(self, node: str, state: dict[str, Any]) -> None:
        self._counter += 1
        path = self.run_dir / "state_snapshots" / f"{self._counter:03d}_{node}.json"
        self._write_json(path, _safe_json(state))

    def agent_call(
        self,
        *,
        agent_name: str,
        prompt_version: str,
        model_name: str,
        temperature: float,
        input_summary: dict[str, Any],
        prompt: str,
        raw_response: str,
        parsed: dict[str, Any] | None,
        errors: list[str] | None,
        retry_count: int,
        retry_events: list[dict[str, Any]] | None = None,
        latency_seconds: float,
        token_usage: dict[str, Any] | None = None,
    ) -> None:
        self._counter += 1
        prefix = f"{self._counter:03d}_{agent_name}"
        meta = {
            "agent_name": agent_name,
            "prompt_version": prompt_version,
            "model_name": model_name,
            "temperature": temperature,
            "timestamp": _utc_like_now(),
            "input_summary": input_summary,
            "errors": errors or [],
            "retry_count": retry_count,
            "retry_events": retry_events or [],
            "latency_seconds": latency_seconds,
            "token_usage": token_usage or {},
        }
        self._write_json(self.run_dir / "responses" / f"{prefix}.meta.json", meta)
        if self.log_level == "debug" and self.keep_full_prompts:
            (self.run_dir / "prompts" / f"{prefix}.prompt.txt").write_text(
                prompt,
                encoding="utf-8",
            )
        (self.run_dir / "responses" / f"{prefix}.raw.txt").write_text(
            raw_response or "",
            encoding="utf-8",
        )
        if parsed is not None:
            self._write_json(
                self.run_dir / "responses" / f"{prefix}.parsed.json",
                parsed,
            )

    def candidates(
        self,
        *,
        raw: list[dict[str, Any]],
        verified: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
    ) -> None:
        self._write_json(self.run_dir / "candidates" / "raw_candidates.json", raw)
        self._write_json(
            self.run_dir / "candidates" / "verified_candidates.json",
            verified,
        )
        self._write_json(
            self.run_dir / "candidates" / "rejected_candidates.json",
            rejected,
        )

    def tool_call(
        self,
        *,
        agent_name: str,
        tool_name: str,
        args_summary: dict[str, Any],
        result_summary: dict[str, Any],
        latency_seconds: float,
        args: dict[str, Any] | None = None,
        result: Any | None = None,
        error: str = "",
    ) -> None:
        self._counter += 1
        payload = {
            "agent_name": agent_name,
            "tool_name": tool_name,
            "timestamp": _utc_like_now(),
            "args": args or {},
            "args_summary": args_summary,
            "result": result,
            "result_summary": result_summary,
            "latency_seconds": latency_seconds,
            "error": error,
        }
        self._write_json(
            self.run_dir
            / "tool_calls"
            / f"{self._counter:03d}_{agent_name}_{tool_name}.json",
            payload,
        )

    def final_outputs(
        self,
        *,
        final_patch: dict[str, Any],
        final_memory: dict[str, Any],
        report: dict[str, Any],
    ) -> None:
        self._write_json(self.run_dir / "final_patch.json", final_patch)
        self._write_json(self.run_dir / "final_memory.json", final_memory)
        self._write_json(self.run_dir / "report.json", report)
        (self.run_dir / "report.md").write_text(
            _render_report(report),
            encoding="utf-8",
        )

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_safe_json(data), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def timed() -> float:
    return time.perf_counter()


def elapsed(start: float) -> float:
    return round(time.perf_counter() - start, 4)


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_json(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _utc_like_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _render_report(report: dict[str, Any]) -> str:
    lines = [
        "# Short-Term LangGraph Update Report",
        "",
        f"- run_id: {report.get('run_id', '')}",
        f"- meeting_id: {report.get('meeting_id', '')}",
        f"- processed_until_line: {report.get('processed_until_line', '')}",
        f"- transcript_line_count: {report.get('transcript_line_count', '')}",
        "",
        "## Candidate Counts",
    ]
    counts = report.get("candidate_counts", {})
    if isinstance(counts, dict):
        for key, value in counts.items():
            lines.append(f"- {key}: {value}")
    lines.extend(["", "## Rejections"])
    rejection_counts = report.get("rejection_counts", {})
    if isinstance(rejection_counts, dict) and rejection_counts:
        for reason, value in rejection_counts.items():
            lines.append(f"- {reason}: {value}")
    else:
        lines.append("- none")
    warning_counts = report.get("warning_counts", {})
    lines.extend(["", "## Candidate Warnings"])
    if isinstance(warning_counts, dict) and warning_counts:
        for warning, value in warning_counts.items():
            lines.append(f"- {warning}: {value}")
    else:
        lines.append("- none")
    operations = report.get("staged_operations", {})
    lines.extend(["", "## Staged Operations"])
    if isinstance(operations, dict) and operations:
        for operation, value in operations.items():
            lines.append(f"- {operation}: {value}")
    else:
        lines.append("- none")
    final_writes = report.get("final_writes", [])
    lines.extend(["", "## Final Writes"])
    if isinstance(final_writes, list) and final_writes:
        for row in final_writes:
            if isinstance(row, dict):
                lines.append(
                    "- "
                    f"{row.get('section', '')} "
                    f"{row.get('operation', '')} "
                    f"target={row.get('target_id', '')} "
                    f"candidate={row.get('candidate_id', '')}"
                )
    else:
        lines.append("- none")
    lines.extend(["", "## Final"])
    final = report.get("final", {})
    if isinstance(final, dict):
        for key, value in final.items():
            lines.append(f"- {key}: {value}")
    warnings = report.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings"])
        for warning in warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines) + "\n"
