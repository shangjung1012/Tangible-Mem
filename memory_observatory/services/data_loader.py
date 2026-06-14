from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .datasets import DatasetConfig, resolve_dataset


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path, default: Any | None = None) -> Any:
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _split_csv_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []
    return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]


def _normalize_eval_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    normalized = dict(row)
    query_id = str(row.get("query_id") or row.get("question_id") or f"q{index:03d}")
    normalized["query_id"] = query_id
    normalized["question_id"] = str(row.get("question_id") or query_id)
    normalized["query"] = str(row.get("query") or row.get("question") or "")
    normalized["question"] = normalized["query"]
    if "expected_obj_ids" not in normalized:
        normalized["expected_obj_ids"] = _split_csv_list(row.get("gold_l1_obj_ids") or row.get("strict_gold_obj_ids"))
    else:
        normalized["expected_obj_ids"] = _split_csv_list(normalized.get("expected_obj_ids"))
    for field in ("strict_gold_obj_ids", "acceptable_obj_ids", "expected_l2_ids", "expected_l3_ids", "gold_meeting_ids"):
        if field in normalized:
            normalized[field] = _split_csv_list(normalized.get(field))
    return normalized


def _normalize_child_l2_node(child: dict[str, Any]) -> dict[str, Any]:
    row = dict(child)
    child_id = row.get("l2_id") or row.get("child_l2_id")
    if child_id:
        row["l2_id"] = str(child_id)
        row.setdefault("child_l2_id", str(child_id))
    return row


def _normalize_l3_node(node: dict[str, Any]) -> dict[str, Any]:
    row = dict(node)
    row["l3_id"] = str(row.get("l3_id") or row.get("parent_l3_id") or "")
    row["label"] = str(row.get("label") or row.get("parent_l3_label") or row.get("l3_label") or row["l3_id"])
    children = row.get("child_l2_nodes", []) or []
    row["child_l2_nodes"] = [
        _normalize_child_l2_node(child)
        for child in children
        if isinstance(child, dict)
    ]
    if "event_count" not in row:
        linked_obj_ids = row.get("linked_obj_ids", []) or []
        row["event_count"] = len(linked_obj_ids)
    return row


def _normalize_l3_view(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    row = dict(data)
    nodes = row.get("l3_nodes")
    if not isinstance(nodes, list):
        nodes = row.get("l3_parents", [])
    row["l3_nodes"] = [
        _normalize_l3_node(node)
        for node in (nodes or [])
        if isinstance(node, dict)
    ]
    row.setdefault("materialized_l3_count", len(row["l3_nodes"]))
    return row


class ObservatoryDataLoader:
    def __init__(self, repo_root: Path | str = REPO_ROOT, dataset_id: str | None = "grace") -> None:
        self.repo_root = Path(repo_root)
        self.dataset: DatasetConfig = resolve_dataset(self.repo_root, dataset_id)

    @property
    def share_mem_root(self) -> Path:
        return self.dataset.share_mem_root

    @property
    def transcript_root(self) -> Path:
        if self.dataset.dataset_id == "icsi":
            return self.repo_root / "meeting_recording" / "transcript" / "ISCI"
        return self.repo_root / "meeting_recording" / "transcript" / "grace"

    def path(self, *parts: str) -> Path:
        return self.repo_root.joinpath(*parts)

    def load_share_tree(self) -> dict[str, Any]:
        data = load_json(self.share_mem_root / "tree.json", {})
        return data if isinstance(data, dict) else {}

    def iter_meetings(self) -> list[dict[str, Any]]:
        meetings = self.load_share_tree().get("meetings", [])
        return meetings if isinstance(meetings, list) else []

    def iter_l1_objects(self) -> list[dict[str, Any]]:
        objects: list[dict[str, Any]] = []
        for meeting in self.iter_meetings():
            meeting_id = str(meeting.get("meeting_id", "") or "")
            meeting_date = str(meeting.get("meeting_date", "") or "")
            source_file = str(meeting.get("source_file", "") or "")
            for obj in meeting.get("memory_objects", []) or []:
                if not isinstance(obj, dict):
                    continue
                row = dict(obj)
                row.setdefault("meeting_id", meeting_id)
                row.setdefault("meeting_date", meeting_date)
                row.setdefault("source_file", source_file)
                objects.append(row)
        return objects

    def object_by_id(self) -> dict[str, dict[str, Any]]:
        return {str(obj.get("obj_id", "")): obj for obj in self.iter_l1_objects() if obj.get("obj_id")}

    def load_l2_view(self) -> dict[str, Any]:
        data = load_json(self.dataset.l2_root / "l2_view.json", {})
        return data if isinstance(data, dict) else {}

    def load_l2_index(self) -> dict[str, Any]:
        data = load_json(self.dataset.l2_root / "l2_index.json", {})
        return data if isinstance(data, dict) else {}

    def load_l3_view(self) -> dict[str, Any]:
        data = load_json(self.dataset.l3_root / "l3_view.json", {})
        return _normalize_l3_view(data if isinstance(data, dict) else {})

    def load_l3_index(self) -> dict[str, Any]:
        data = load_json(self.dataset.l3_root / "l3_index.json", {})
        return data if isinstance(data, dict) else {}

    def load_l3_validation(self) -> dict[str, Any]:
        data = load_json(self.dataset.l3_validation_path, {})
        return data if isinstance(data, dict) else {}

    def load_l2_validation(self) -> dict[str, Any]:
        data = load_json(self.dataset.l2_validation_path, {})
        return data if isinstance(data, dict) else {}

    def load_retrieval_eval_report(self) -> dict[str, Any]:
        data = load_json(self.dataset.retrieval_eval_report_path, {})
        return data if isinstance(data, dict) else {}

    def load_system_comparison_summary(self) -> dict[str, Any]:
        if not self.dataset.system_comparison_path:
            return {}
        data = load_json(self.dataset.system_comparison_path, {})
        return data if isinstance(data, dict) else {}

    def load_topic_surface_ablation(self) -> dict[str, Any]:
        if not self.dataset.topic_surface_ablation_path:
            return {}
        data = load_json(self.dataset.topic_surface_ablation_path, {})
        return data if isinstance(data, dict) else {}

    def load_eval_queries(self, path: Path | str | None = None) -> list[dict[str, Any]]:
        query_path = Path(path) if path else self.repo_root / "long_term" / "eval" / "long_term_retrieval_queries.jsonl"
        if not query_path.is_absolute():
            query_path = self.repo_root / query_path
        if not query_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        if query_path.suffix.lower() == ".csv":
            with query_path.open(newline="", encoding="utf-8-sig") as f:
                for index, row in enumerate(csv.DictReader(f), start=1):
                    rows.append(_normalize_eval_row(dict(row), index))
            return rows
        for line in query_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if isinstance(data, dict):
                rows.append(_normalize_eval_row(data, len(rows) + 1))
        return rows

    def load_transcripts(self) -> dict[str, str]:
        transcripts: dict[str, str] = {}
        for path in sorted(self.transcript_root.glob("*.txt")):
            transcripts[path.stem] = path.read_text(encoding="utf-8", errors="replace")
        return transcripts
