from __future__ import annotations

from pathlib import Path
from typing import Any

from .data_loader import ObservatoryDataLoader


class TopicStore:
    def __init__(self, repo_root: Path | str) -> None:
        self.loader = ObservatoryDataLoader(repo_root)

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
        unpromoted = [
            {
                "l2_id": node.get("l2_id"),
                "label": node.get("label"),
                "event_count": len(node.get("linked_obj_ids", []) or node.get("timeline_digest", []) or []),
            }
            for node in self.l2_nodes()
            if str(node.get("l2_id", "") or "") not in promoted_source_ids
        ]
        return {
            "l3_nodes": self.l3_nodes(),
            "unpromoted_l2_nodes": unpromoted,
        }

    def get_l2(self, l2_id: str) -> dict[str, Any] | None:
        for node in self.l2_nodes():
            if node.get("l2_id") == l2_id:
                return node
        for l3 in self.l3_nodes():
            for child in l3.get("child_l2_nodes", []) or []:
                if child.get("l2_id") == l2_id:
                    enriched = dict(child)
                    enriched["parent_l3_id"] = l3.get("l3_id")
                    enriched["parent_l3_label"] = l3.get("label")
                    return enriched
        return None

    def get_l3(self, l3_id: str) -> dict[str, Any] | None:
        for node in self.l3_nodes():
            if node.get("l3_id") == l3_id:
                return node
        return None

    def topic_link_for_obj(self, obj_id: str) -> dict[str, Any]:
        l2 = self.l2_index().get(obj_id, {})
        l3 = self.l3_index().get(obj_id, {})
        return {
            "obj_id": obj_id,
            "l2_id": l2.get("l2_id"),
            "l2_label": l2.get("l2_label") or l2.get("label"),
            "assignment_reason": l2.get("assignment_reason"),
            "confidence": l2.get("confidence"),
            "parent_l3_id": l3.get("l3_id"),
            "child_l2_id": l3.get("child_l2_id"),
            "child_l2_label": l3.get("child_l2_label"),
            "l3_assignment_reason": l3.get("assignment_reason"),
            "l3_assignment_score": l3.get("assignment_score"),
        }

