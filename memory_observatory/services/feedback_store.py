from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .data_loader import load_json, write_json


class FeedbackStore:
    def __init__(self, share_mem_root: Path | str) -> None:
        self.share_mem_root = Path(share_mem_root)
        self.root = self.share_mem_root / "user_feedback"
        self.adjustments_path = self.root / "importance_adjustments.jsonl"
        self.index_path = self.root / "importance_override_index.json"
        self.summary_path = self.root / "importance_feedback_summary.json"

    def load_adjustments(self) -> list[dict[str, Any]]:
        if not self.adjustments_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.adjustments_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def load_override_index(self) -> dict[str, Any]:
        data = load_json(self.index_path, {})
        return data if isinstance(data, dict) else {}

    def load_summary(self) -> dict[str, Any]:
        data = load_json(self.summary_path, {})
        return data if isinstance(data, dict) else {}

    def save_importance_adjustment(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        rows = self.load_adjustments()
        feedback_id = f"FB-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{len(rows) + 1:04d}"
        canonical = float(payload.get("canonical_importance", 0.0) or 0.0)
        user_importance = max(0.0, min(1.0, float(payload.get("user_importance", canonical) or canonical)))
        record = {
            "feedback_id": feedback_id,
            "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reviewer": payload.get("reviewer", "user"),
            "obj_id": payload.get("obj_id", ""),
            "meeting_id": payload.get("meeting_id", ""),
            "object_type": payload.get("object_type", payload.get("type", "")),
            "linked_l2_id": payload.get("linked_l2_id", payload.get("l2_id", "")),
            "child_l2_id": payload.get("child_l2_id", ""),
            "parent_l3_id": payload.get("parent_l3_id", ""),
            "canonical_importance": canonical,
            "user_importance": user_importance,
            "effective_importance": user_importance,
            "delta": round(user_importance - canonical, 4),
            "reason_code": payload.get("reason_code", "other"),
            "note": payload.get("note", ""),
            "source": "memory_observatory",
        }
        with self.adjustments_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        rows.append(record)
        self._write_index_and_summary(rows)
        return record

    def _write_index_and_summary(self, rows: list[dict[str, Any]]) -> None:
        index: dict[str, Any] = {}
        for row in rows:
            obj_id = str(row.get("obj_id", "") or "")
            if not obj_id:
                continue
            index[obj_id] = {
                "latest_feedback_id": row.get("feedback_id"),
                "canonical_importance": row.get("canonical_importance"),
                "effective_importance": row.get("effective_importance"),
                "delta": row.get("delta"),
                "reason_code": row.get("reason_code"),
            }
        write_json(self.index_path, index)

        by_type = Counter(str(row.get("object_type", "") or "unknown") for row in rows)
        by_reason = Counter(str(row.get("reason_code", "") or "other") for row in rows)
        by_l2 = Counter(str(row.get("linked_l2_id", "") or "unlinked") for row in rows)
        by_meeting = Counter(str(row.get("meeting_id", "") or "unknown") for row in rows)
        deltas_by_type: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            deltas_by_type[str(row.get("object_type", "") or "unknown")].append(float(row.get("delta", 0.0) or 0.0))
        summary = {
            "total_feedback_count": len(rows),
            "adjusted_up_count": sum(1 for row in rows if float(row.get("delta", 0.0) or 0.0) > 0),
            "adjusted_down_count": sum(1 for row in rows if float(row.get("delta", 0.0) or 0.0) < 0),
            "by_type": dict(by_type),
            "by_reason_code": dict(by_reason),
            "by_l2": dict(by_l2),
            "by_meeting": dict(by_meeting),
            "avg_delta_by_type": {
                key: round(sum(values) / max(1, len(values)), 4)
                for key, values in deltas_by_type.items()
            },
            "most_adjusted_objects": sorted(
                index.items(),
                key=lambda item: abs(float(item[1].get("delta", 0.0) or 0.0)),
                reverse=True,
            )[:20],
        }
        write_json(self.summary_path, summary)

