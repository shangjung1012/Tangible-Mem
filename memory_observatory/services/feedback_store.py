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
        self.summary_corrections_path = self.root / "summary_corrections.jsonl"
        self.summary_correction_index_path = self.root / "summary_correction_index.json"
        self.validity_flags_path = self.root / "validity_flags.jsonl"
        self.validity_flag_index_path = self.root / "validity_flag_index.json"
        self.topic_link_reviews_path = self.root / "topic_link_reviews.jsonl"
        self.topic_link_review_index_path = self.root / "topic_link_review_index.json"
        self.correction_summary_path = self.root / "correction_feedback_summary.json"

    def _load_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _next_id(self, prefix: str, existing_count: int) -> str:
        return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{existing_count + 1:04d}"

    def _created_at(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def load_adjustments(self) -> list[dict[str, Any]]:
        return self._load_jsonl(self.adjustments_path)

    def load_override_index(self) -> dict[str, Any]:
        data = load_json(self.index_path, {})
        return data if isinstance(data, dict) else {}

    def load_summary(self) -> dict[str, Any]:
        data = load_json(self.summary_path, {})
        return data if isinstance(data, dict) else {}

    def save_importance_adjustment(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        rows = self.load_adjustments()
        feedback_id = self._next_id("FB", len(rows))
        canonical = float(payload.get("canonical_importance", 0.0) or 0.0)
        user_importance = max(0.0, min(1.0, float(payload.get("user_importance", canonical) or canonical)))
        record = {
            "feedback_id": feedback_id,
            "created_at_utc": self._created_at(),
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
        self._append_jsonl(self.adjustments_path, record)
        rows.append(record)
        self._write_index_and_summary(rows)
        return record

    def load_summary_corrections(self) -> list[dict[str, Any]]:
        return self._load_jsonl(self.summary_corrections_path)

    def load_validity_flags(self) -> list[dict[str, Any]]:
        return self._load_jsonl(self.validity_flags_path)

    def load_topic_link_reviews(self) -> list[dict[str, Any]]:
        return self._load_jsonl(self.topic_link_reviews_path)

    def load_correction_summary(self) -> dict[str, Any]:
        data = load_json(self.correction_summary_path, {})
        return data if isinstance(data, dict) else {}

    def save_summary_correction(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = self.load_summary_corrections()
        record = {
            "correction_id": self._next_id("SC", len(rows)),
            "created_at_utc": self._created_at(),
            "reviewer": payload.get("reviewer", "user"),
            "obj_id": payload.get("obj_id", ""),
            "meeting_id": payload.get("meeting_id", ""),
            "canonical_content": payload.get("canonical_content", ""),
            "corrected_content": payload.get("corrected_content", ""),
            "reason_code": payload.get("reason_code", "other"),
            "note": payload.get("note", ""),
            "status": payload.get("status", "accepted"),
            "source": "memory_observatory",
            "applies_to": "effective_memory_view",
        }
        self._append_jsonl(self.summary_corrections_path, record)
        rows.append(record)
        self._write_correction_indexes_and_summary()
        return record

    def save_validity_flag(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = self.load_validity_flags()
        record = {
            "flag_id": self._next_id("VF", len(rows)),
            "created_at_utc": self._created_at(),
            "reviewer": payload.get("reviewer", "user"),
            "obj_id": payload.get("obj_id", ""),
            "meeting_id": payload.get("meeting_id", ""),
            "flag_type": payload.get("flag_type", "needs_review"),
            "reason_code": payload.get("reason_code", "other"),
            "note": payload.get("note", ""),
            "status": payload.get("status", "accepted"),
            "source": "memory_observatory",
            "applies_to": "effective_memory_view",
        }
        self._append_jsonl(self.validity_flags_path, record)
        rows.append(record)
        self._write_correction_indexes_and_summary()
        return record

    def save_topic_link_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = self.load_topic_link_reviews()
        record = {
            "review_id": self._next_id("TL", len(rows)),
            "created_at_utc": self._created_at(),
            "reviewer": payload.get("reviewer", "user"),
            "obj_id": payload.get("obj_id", ""),
            "meeting_id": payload.get("meeting_id", ""),
            "action": payload.get("action", "review"),
            "l2_id": payload.get("l2_id", ""),
            "l2_label": payload.get("l2_label", ""),
            "child_l2_id": payload.get("child_l2_id", ""),
            "parent_l3_id": payload.get("parent_l3_id", ""),
            "reason_code": payload.get("reason_code", "other"),
            "note": payload.get("note", ""),
            "status": payload.get("status", "accepted"),
            "source": "memory_observatory",
            "applies_to": "effective_topic_view",
        }
        self._append_jsonl(self.topic_link_reviews_path, record)
        rows.append(record)
        self._write_correction_indexes_and_summary()
        return record

    def load_object_corrections(self, obj_id: str) -> dict[str, Any]:
        target = str(obj_id)
        return {
            "obj_id": target,
            "summary_corrections": [
                row for row in self.load_summary_corrections() if str(row.get("obj_id", "")) == target
            ],
            "validity_flags": [
                row for row in self.load_validity_flags() if str(row.get("obj_id", "")) == target
            ],
            "topic_link_reviews": [
                row for row in self.load_topic_link_reviews() if str(row.get("obj_id", "")) == target
            ],
        }

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

    def _latest_by_object(self, rows: list[dict[str, Any]], id_key: str) -> dict[str, Any]:
        index: dict[str, Any] = {}
        for row in rows:
            obj_id = str(row.get("obj_id", "") or "")
            if not obj_id:
                continue
            index[obj_id] = {
                "latest_id": row.get(id_key),
                "status": row.get("status"),
                "reason_code": row.get("reason_code"),
                "created_at_utc": row.get("created_at_utc"),
            }
        return index

    def _write_correction_indexes_and_summary(self) -> None:
        summary_rows = self.load_summary_corrections()
        validity_rows = self.load_validity_flags()
        topic_rows = self.load_topic_link_reviews()
        write_json(self.summary_correction_index_path, self._latest_by_object(summary_rows, "correction_id"))
        write_json(self.validity_flag_index_path, self._latest_by_object(validity_rows, "flag_id"))
        write_json(self.topic_link_review_index_path, self._latest_by_object(topic_rows, "review_id"))

        by_flag = Counter(str(row.get("flag_type", "") or "unknown") for row in validity_rows)
        by_action = Counter(str(row.get("action", "") or "review") for row in topic_rows)
        summary = {
            "summary_correction_count": len(summary_rows),
            "validity_flag_count": len(validity_rows),
            "topic_link_review_count": len(topic_rows),
            "total_correction_count": len(summary_rows) + len(validity_rows) + len(topic_rows),
            "by_validity_flag_type": dict(by_flag),
            "by_topic_link_action": dict(by_action),
            "raw_l1_mutation_policy": "raw transcript evidence and raw L1 provenance remain immutable",
            "effective_view_policy": "accepted sidecars define the effective memory surface",
        }
        write_json(self.correction_summary_path, summary)
