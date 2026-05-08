from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SHARE_MEM_SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHARE_MEM_ROOT = REPO_ROOT / "share_mem"

GENERATED_FILE_NAMES = (
    "tree.json",
    "l1_index.json",
    "manifest.json",
    "l1_quality_index.json",
    "memory_relations_index.json",
    "memory_activity_index.json",
    "topic_tree.json",
    "topic_index.json",
)
GENERATED_DIR_NAMES = (
    "meetings",
    "snapshots",
    "research_logs",
    "topic_updates",
    "topic_research_logs",
)


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def empty_share_tree() -> dict[str, Any]:
    return {
        "tree_version": 0,
        "last_updated_utc": "",
        "project_profile": {},
        "phases": [],
        "meetings": [],
    }


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _meeting_sort_value(meeting: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(meeting.get("meeting_date", "") or ""),
        str(meeting.get("timestamp", "") or ""),
        str(meeting.get("meeting_id", "") or ""),
    )


def normalize_share_tree(tree: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(tree if isinstance(tree, dict) else empty_share_tree())
    normalized.setdefault("tree_version", 0)
    normalized.setdefault("last_updated_utc", "")
    normalized.setdefault("project_profile", {})
    normalized.setdefault("phases", [])
    meetings = [
        meeting
        for meeting in normalized.get("meetings", [])
        if isinstance(meeting, dict) and str(meeting.get("meeting_id", "")).strip()
    ]
    meetings.sort(key=_meeting_sort_value)
    normalized["meetings"] = meetings
    return normalized


def load_share_tree(
    root: Path | str = DEFAULT_SHARE_MEM_ROOT,
    *,
    tree_path: Path | str | None = None,
) -> dict[str, Any]:
    path = Path(tree_path) if tree_path is not None else Path(root) / "tree.json"
    if not path.exists():
        return empty_share_tree()
    data = _load_json(path)
    if not isinstance(data, dict):
        raise RuntimeError(f"share_mem tree must be a JSON object: {path}")
    return normalize_share_tree(data)


def iter_meetings(tree: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for meeting in normalize_share_tree(tree).get("meetings", []):
        yield meeting


def iter_l1_objects(tree: dict[str, Any]) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    for meeting in iter_meetings(tree):
        for obj in meeting.get("memory_objects", []):
            if isinstance(obj, dict) and str(obj.get("obj_id", "")).strip():
                yield meeting, obj


def build_l1_index(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for meeting, obj in iter_l1_objects(tree):
        obj_id = str(obj.get("obj_id", "")).strip()
        raw_topics = obj.get("related_topics", [])
        topics = [str(topic) for topic in raw_topics] if isinstance(raw_topics, list) else []
        index[obj_id] = {
            "obj_id": obj_id,
            "meeting_id": str(meeting.get("meeting_id", "") or ""),
            "meeting_date": str(meeting.get("meeting_date", "") or ""),
            "timestamp": str(meeting.get("timestamp", "") or ""),
            "source_file": str(meeting.get("source_file", "") or ""),
            "type": str(obj.get("type", "") or ""),
            "content": str(obj.get("content", "") or ""),
            "evidence": str(obj.get("evidence", "") or ""),
            "importance": obj.get("importance", 0.0),
            "topics": topics,
        }
    return dict(sorted(index.items()))


def get_l1_object(
    obj_id: str,
    *,
    tree: dict[str, Any] | None = None,
    root: Path | str = DEFAULT_SHARE_MEM_ROOT,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    wanted = str(obj_id).strip()
    if not wanted:
        return None
    search_tree = tree if tree is not None else load_share_tree(root)
    for meeting, obj in iter_l1_objects(search_tree):
        if str(obj.get("obj_id", "")).strip() == wanted:
            return meeting, obj
    return None


def load_recent_meetings(
    limit: int = 3,
    *,
    tree: dict[str, Any] | None = None,
    root: Path | str = DEFAULT_SHARE_MEM_ROOT,
) -> list[dict[str, Any]]:
    search_tree = tree if tree is not None else load_share_tree(root)
    meetings = list(iter_meetings(search_tree))
    if limit <= 0:
        return []
    return meetings[-limit:]


def _tree_hash(tree: dict[str, Any]) -> str:
    payload = json.dumps(tree, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_manifest(
    *,
    root: Path,
    tree: dict[str, Any],
    source_transcript_dir: Path | None,
) -> dict[str, Any]:
    meetings = list(iter_meetings(tree))
    index = build_l1_index(tree)
    topic_view = build_topic_view_manifest(root)
    return {
        "schema_version": SHARE_MEM_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "source_transcript_dir": str(source_transcript_dir.resolve())
        if source_transcript_dir is not None
        else "",
        "tree_path": str((root / "tree.json").resolve()),
        "meeting_count": len(meetings),
        "object_count": len(index),
        "meeting_ids": [str(meeting.get("meeting_id", "") or "") for meeting in meetings],
        "tree_hash": _tree_hash(tree),
        "topic_view": topic_view,
    }


def build_topic_view_manifest(root: Path) -> dict[str, Any]:
    topic_tree_path = root / "topic_tree.json"
    topic_index_path = root / "topic_index.json"
    if not topic_tree_path.exists() or not topic_index_path.exists():
        return {
            "exists": False,
            "topic_count": 0,
            "topic_event_count": 0,
            "topic_tree_path": str(topic_tree_path.resolve()),
            "topic_index_path": str(topic_index_path.resolve()),
        }
    topic_tree = _load_json(topic_tree_path)
    topic_index = _load_json(topic_index_path)
    roots = [
        root_node
        for root_node in topic_tree.get("topic_roots", [])
        if isinstance(root_node, dict)
    ] if isinstance(topic_tree, dict) else []
    child_count = sum(
        len([child for child in root_node.get("children", []) if isinstance(child, dict)])
        for root_node in roots
    )
    return {
        "exists": True,
        "topic_count": child_count,
        "topic_event_count": len(topic_index) if isinstance(topic_index, dict) else 0,
        "topic_tree_path": str(topic_tree_path.resolve()),
        "topic_index_path": str(topic_index_path.resolve()),
    }


def clean_generated_outputs(root: Path | str = DEFAULT_SHARE_MEM_ROOT) -> None:
    base = Path(root).resolve()
    for file_name in GENERATED_FILE_NAMES:
        path = base / file_name
        if path.exists():
            path.unlink()
    for dir_name in GENERATED_DIR_NAMES:
        path = base / dir_name
        if path.exists():
            shutil.rmtree(path)


def refresh_share_mem_outputs(
    *,
    root: Path | str = DEFAULT_SHARE_MEM_ROOT,
    tree: dict[str, Any],
    source_transcript_dir: Path | str | None = None,
) -> dict[str, Any]:
    base = Path(root)
    normalized_tree = normalize_share_tree(tree)
    meetings_dir = base / "meetings"
    if meetings_dir.exists():
        shutil.rmtree(meetings_dir)
    meetings_dir.mkdir(parents=True, exist_ok=True)

    _write_json(base / "tree.json", normalized_tree)
    for meeting in iter_meetings(normalized_tree):
        meeting_id = str(meeting.get("meeting_id", "")).strip()
        _write_json(meetings_dir / f"{meeting_id}.json", meeting)

    index = build_l1_index(normalized_tree)
    _write_json(base / "l1_index.json", index)

    source_dir = Path(source_transcript_dir) if source_transcript_dir is not None else None
    manifest = build_manifest(
        root=base,
        tree=normalized_tree,
        source_transcript_dir=source_dir,
    )
    _write_json(base / "manifest.json", manifest)
    return manifest
