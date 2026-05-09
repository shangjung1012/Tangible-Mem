from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .data_loader import load_json, write_json


class ReportStore:
    def __init__(self, runs_root: Path | str) -> None:
        self.runs_root = Path(runs_root)

    def create_run_dir(self, prefix: str = "run") -> Path:
        self.runs_root.mkdir(parents=True, exist_ok=True)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if prefix:
            run_id = f"{prefix}_{run_id}"
        run_dir = self.runs_root / run_id
        suffix = 1
        while run_dir.exists():
            run_dir = self.runs_root / f"{run_id}_{suffix}"
            suffix += 1
        run_dir.mkdir(parents=True)
        return run_dir

    def write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_json(self, path: Path, data: Any) -> None:
        write_json(path, data)

    def write_run(self, run_dir: Path, result: dict[str, Any]) -> None:
        self.write_json(run_dir / "results.json", result)
        self.write_json(run_dir / "summary.json", result.get("summary", {}))
        self.write_json(run_dir / "visualization_data.json", result)

    def list_runs(self) -> list[dict[str, Any]]:
        if not self.runs_root.exists():
            return []
        rows: list[dict[str, Any]] = []
        for child in sorted(self.runs_root.iterdir(), key=lambda p: p.name, reverse=True):
            if not child.is_dir():
                continue
            results_path = child / "results.json"
            summary = load_json(child / "summary.json", {})
            rows.append(
                {
                    "run_id": child.name,
                    "path": str(child),
                    "has_results": results_path.exists(),
                    "summary": summary if isinstance(summary, dict) else {},
                }
            )
        return rows

    def load_run(self, run_id: str) -> dict[str, Any]:
        path = self.runs_root / run_id / "results.json"
        data = load_json(path, {})
        return data if isinstance(data, dict) else {}

    def load_query(self, run_id: str, query_id: str) -> dict[str, Any]:
        data = load_json(self.runs_root / run_id / "results_by_query" / f"{query_id}.json", {})
        return data if isinstance(data, dict) else {}

    def load_context(self, run_id: str, query_id: str, strategy: str) -> str:
        path = self.runs_root / run_id / "contexts" / query_id / f"{strategy}.txt"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def load_answer(self, run_id: str, query_id: str, strategy: str) -> str:
        path = self.runs_root / run_id / "answers" / query_id / f"{strategy}.txt"
        return path.read_text(encoding="utf-8") if path.exists() else ""

