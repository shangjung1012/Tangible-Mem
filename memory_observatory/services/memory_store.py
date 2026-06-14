from __future__ import annotations

from pathlib import Path
from typing import Any

from .data_loader import ObservatoryDataLoader
from .feedback_store import FeedbackStore
from .topic_store import TopicStore


class MemoryStore:
    def __init__(self, repo_root: Path | str, dataset_id: str | None = "grace") -> None:
        self.loader = ObservatoryDataLoader(repo_root, dataset_id=dataset_id)
        self.topic_store = TopicStore(repo_root, dataset_id=dataset_id)
        self.feedback_store = FeedbackStore(self.loader.share_mem_root)

    def meetings(self) -> list[dict[str, Any]]:
        objects_by_meeting: dict[str, list[dict[str, Any]]] = {}
        feedback_index = self.feedback_store.load_override_index()
        for obj in self.loader.iter_l1_objects():
            objects_by_meeting.setdefault(str(obj.get("meeting_id", "")), []).append(obj)
        rows = []
        for meeting in self.loader.iter_meetings():
            meeting_id = str(meeting.get("meeting_id", "") or "")
            objects = objects_by_meeting.get(meeting_id, [])
            rows.append(
                {
                    "meeting_id": meeting_id,
                    "meeting_date": meeting.get("meeting_date", ""),
                    "source_file": meeting.get("source_file", ""),
                    "object_count": len(objects),
                    "high_importance_count": sum(float(obj.get("importance", 0.0) or 0.0) >= 0.7 for obj in objects),
                    "feedback_count": sum(1 for obj in objects if obj.get("obj_id") in feedback_index),
                }
            )
        return rows

    def objects(self, meeting_id: str | None = None) -> list[dict[str, Any]]:
        feedback_index = self.feedback_store.load_override_index()
        rows: list[dict[str, Any]] = []
        for obj in self.loader.iter_l1_objects():
            if meeting_id and str(obj.get("meeting_id", "")) != meeting_id:
                continue
            obj_id = str(obj.get("obj_id", "") or "")
            feedback = feedback_index.get(obj_id, {})
            canonical = float(obj.get("importance", 0.0) or 0.0)
            effective = float(feedback.get("effective_importance", canonical) or canonical)
            link = self.topic_store.topic_link_for_obj(obj_id)
            rows.append(
                {
                    "obj_id": obj_id,
                    "meeting_id": obj.get("meeting_id"),
                    "meeting_date": obj.get("meeting_date"),
                    "type": obj.get("type"),
                    "content": obj.get("content", ""),
                    "content_preview": str(obj.get("content", ""))[:180],
                    "canonical_importance": canonical,
                    "effective_importance": effective,
                    "importance_delta": round(effective - canonical, 4),
                    "related_topics": obj.get("related_topics", []),
                    "topic_link": link,
                    "has_feedback": bool(feedback),
                }
            )
        return rows

    def object_detail(self, obj_id: str) -> dict[str, Any] | None:
        obj = self.loader.object_by_id().get(obj_id)
        if not obj:
            return None
        feedback_rows = [
            row for row in self.feedback_store.load_adjustments() if row.get("obj_id") == obj_id
        ]
        return {
            "details": obj,
            "topic_link": self.topic_store.topic_link_for_obj(obj_id),
            "feedback_history": feedback_rows,
            "lineage_lite": {
                "evidence": obj.get("evidence", ""),
                "l1_object": obj_id,
                "topic_link": self.topic_store.topic_link_for_obj(obj_id),
                "retrieval_traces": [],
            },
        }
