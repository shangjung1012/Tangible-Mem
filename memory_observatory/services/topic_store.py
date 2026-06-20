from __future__ import annotations

from pathlib import Path
from typing import Any

from .data_loader import ObservatoryDataLoader
from .feedback_store import FeedbackStore


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class TopicStore:
    def __init__(self, repo_root: Path | str, dataset_id: str | None = "grace") -> None:
        self.loader = ObservatoryDataLoader(repo_root, dataset_id=dataset_id)
        self.feedback_store = FeedbackStore(self.loader.share_mem_root)

    def l2_nodes(self) -> list[dict[str, Any]]:
        nodes = self.loader.load_l2_view().get("l2_nodes", [])
        return nodes if isinstance(nodes, list) else []

    def l3_nodes(self) -> list[dict[str, Any]]:
        nodes = self.loader.load_l3_view().get("l3_nodes", [])
        return nodes if isinstance(nodes, list) else []

    def l2_index(self) -> dict[str, Any]:
        return self.loader.load_l2_index()

    def l3_index(self) -> dict[str, Any]:
        return self.loader.load_l3_index()

    def linked_l1_ids(self) -> set[str]:
        return set(self.l2_index())

    def hierarchy(self) -> dict[str, Any]:
        promoted_source_ids = {
            str(node.get("promoted_from_l2_id", "") or "")
            for l3 in self.l3_nodes()
            for node in (l3.get("child_l2_nodes", []) or [])
        }
        promoted_source_ids.update(
            str(l3.get("source_l2_id", "") or "")
            for l3 in self.l3_nodes()
            if l3.get("source_l2_id")
        )
        l3_nodes: list[dict[str, Any]] = []
        for l3 in self.l3_nodes():
            row = dict(l3)
            row["child_l2_nodes"] = [
                self._enrich_l2_node(child, parent_l3=l3, include_objects=False)
                for child in (l3.get("child_l2_nodes", []) or [])
                if isinstance(child, dict)
            ]
            row["child_l2_count"] = len(row["child_l2_nodes"])
            row["event_count"] = sum(
                int(child.get("event_count", 0) or 0)
                for child in row["child_l2_nodes"]
            )
            l3_nodes.append(row)
        unpromoted = [
            self._enrich_l2_node(node, include_objects=False)
            for node in self.l2_nodes()
            if str(node.get("l2_id", "") or "") not in promoted_source_ids
        ]
        return {
            "l3_nodes": l3_nodes,
            "unpromoted_l2_nodes": unpromoted,
        }

    def get_l2(self, l2_id: str) -> dict[str, Any] | None:
        base_node: dict[str, Any] | None = None
        for node in self.l2_nodes():
            if node.get("l2_id") == l2_id:
                base_node = node
                break
        for l3 in self.l3_nodes():
            for child in l3.get("child_l2_nodes", []) or []:
                child_id = child.get("l2_id") or child.get("child_l2_id")
                if child_id == l2_id:
                    merged = dict(base_node or {})
                    merged.update(child)
                    return self._enrich_l2_node(merged, parent_l3=l3, include_objects=True)
        if base_node:
            return self._enrich_l2_node(base_node, include_objects=True)
        return None

    def get_l3(self, l3_id: str) -> dict[str, Any] | None:
        for node in self.l3_nodes():
            if node.get("l3_id") == l3_id:
                return node
        return None

    def topic_link_for_obj(self, obj_id: str) -> dict[str, Any]:
        l2 = self.l2_index().get(obj_id, {})
        l3 = self.l3_index().get(obj_id, {})
        parent_l3_id = l3.get("l3_id") or l3.get("parent_l3_id")
        parent_l3_label = l3.get("parent_l3_label") or l3.get("l3_label") or l3.get("label")
        return {
            "obj_id": obj_id,
            "l2_id": l2.get("l2_id"),
            "l2_label": l2.get("l2_label") or l2.get("label"),
            "assignment_reason": l2.get("assignment_reason"),
            "confidence": l2.get("confidence"),
            "parent_l3_id": parent_l3_id,
            "parent_l3_label": parent_l3_label,
            "child_l2_id": l3.get("child_l2_id"),
            "child_l2_label": l3.get("child_l2_label"),
            "l3_assignment_reason": l3.get("assignment_reason"),
            "l3_assignment_score": l3.get("assignment_score"),
        }

    def _linked_obj_ids_for_node(self, node: dict[str, Any]) -> list[str]:
        linked: list[str] = []
        for obj_id in node.get("linked_obj_ids", []) or []:
            if obj_id:
                linked.append(str(obj_id))
        for event in node.get("timeline_digest", []) or []:
            if isinstance(event, dict) and event.get("obj_id"):
                linked.append(str(event.get("obj_id")))
        seen: set[str] = set()
        unique: list[str] = []
        for obj_id in linked:
            if obj_id in seen:
                continue
            seen.add(obj_id)
            unique.append(obj_id)
        return unique

    def _event_count_for_node(self, node: dict[str, Any], linked_obj_ids: list[str]) -> int:
        explicit = node.get("event_count")
        if explicit is not None:
            try:
                return int(explicit)
            except (TypeError, ValueError):
                pass
        return len(linked_obj_ids)

    def _size_bucket(self, event_count: int) -> str:
        if event_count < 3:
            return "tiny"
        if event_count <= 4:
            return "weak"
        if event_count <= 25:
            return "ideal"
        if event_count <= 35:
            return "watch"
        return "oversized"

    def _object_preview(self, obj_id: str) -> dict[str, Any]:
        obj = self.loader.object_by_id().get(obj_id, {})
        feedback = self.feedback_store.load_override_index().get(obj_id, {})
        canonical = _as_float(obj.get("importance"), 0.0)
        effective = _as_float(feedback.get("effective_importance"), canonical)
        return {
            "obj_id": obj_id,
            "meeting_id": obj.get("meeting_id", ""),
            "meeting_date": obj.get("meeting_date", ""),
            "type": obj.get("type", ""),
            "content": obj.get("content", ""),
            "content_preview": str(obj.get("content", ""))[:240],
            "evidence": obj.get("evidence", ""),
            "evidence_preview": str(obj.get("evidence", ""))[:240],
            "related_topics": obj.get("related_topics", []),
            "canonical_importance": canonical,
            "effective_importance": effective,
            "importance_delta": round(effective - canonical, 4),
            "has_feedback": bool(feedback),
            "topic_link": self.topic_link_for_obj(obj_id),
        }

    def _enrich_l2_node(
        self,
        node: dict[str, Any],
        *,
        parent_l3: dict[str, Any] | None = None,
        include_objects: bool,
    ) -> dict[str, Any]:
        linked_obj_ids = self._linked_obj_ids_for_node(node)
        event_count = self._event_count_for_node(node, linked_obj_ids)
        timeline = [
            event
            for event in (node.get("timeline_digest", []) or [])
            if isinstance(event, dict)
        ]
        timeline.sort(key=lambda row: str(row.get("meeting_date") or row.get("meeting_id") or ""))
        row = dict(node)
        row["linked_obj_ids"] = linked_obj_ids
        row["event_count"] = event_count
        row["size_bucket"] = self._size_bucket(event_count)
        row["timeline_digest"] = timeline
        row["timeline_preview"] = timeline[:8]
        row["content_preview"] = str(
            node.get("current_state")
            or node.get("timeline_digest_summary")
            or node.get("definition")
            or node.get("split_reason")
            or ""
        )[:260]
        if parent_l3:
            row["parent_l3_id"] = parent_l3.get("l3_id")
            row["parent_l3_label"] = parent_l3.get("label")
        if include_objects:
            row["linked_l1_objects"] = [self._object_preview(obj_id) for obj_id in linked_obj_ids]
        return row
