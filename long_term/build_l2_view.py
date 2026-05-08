"""Build the active long_term L2 view from canonical share_mem L1 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from share_mem.store import iter_l1_objects, iter_meetings, load_share_tree, normalize_share_tree

L2_VIEW_SCHEMA_VERSION = 1
L2_VIEW_FILE_NAME = "l2_view.json"
L2_INDEX_FILE_NAME = "l2_index.json"
L2_MANIFEST_FILE_NAME = "manifest.json"
L2_UPDATES_DIR_NAME = "l2_updates"
L2_UNLINKED_FILE_NAME = "unlinked_l1_report.json"
L2_RESEARCH_LOGS_DIR_NAME = "research_logs"
SUPPORTED_L2_MODES = {"deterministic", "hybrid"}

TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
SLUG_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)

GENERIC_LABELS = {
    "memory",
    "system",
    "architecture",
    "design",
    "topic",
    "topic tree",
    "topic-tree",
    "data",
    "evaluation",
}

TYPE_LIKE_LABELS = {
    "action item",
    "action_item",
    "approach change",
    "approach_change",
    "argument",
    "decision",
    "design decision",
    "finding",
    "method change",
    "method_change",
    "open issue",
    "open_issue",
    "open question",
    "open_question",
    "proposal",
    "result",
    "todo",
}

RELATED_TOPIC_CANONICAL_LABELS = {
    "alternative approaches": "alternative approaches",
    "data handling": "data handling",
    "data management": "data handling",
    "dataset acquisition": "dataset selection",
    "dataset selection": "dataset selection",
    "development workflow": "development workflow",
    "experimental setup": "research methodology",
    "literature review": "research methodology",
    "long term memory": "stm ltm integration",
    "long term memory architecture": "memory processing architecture",
    "long term memory implementation": "memory system implementation",
    "memory model": "memory processing architecture",
    "memory system architecture": "memory processing architecture",
    "memory system implementation": "memory system implementation",
    "memory system performance": "memory evaluation strategy",
    "model configuration": "model configuration",
    "output quality": "data fragmentation",
    "project goals": "project demo strategy",
    "research methodology": "research methodology",
    "system architecture": "system architecture",
}
RELATED_TOPIC_FALLBACK_MIN_IMPORTANCE = 0.68

ADMINISTRATIVE_HINTS = (
    "meeting room",
    "meeting setup",
    "setup detail",
    "local aside",
    "briefly noted",
    "no long-term memory relevance",
)

CONCEPT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "data fragmentation",
        (
            "fragment",
            "fragmented",
            "fragmentation",
            "chunk",
            "fixed chunk",
            "segment boundary",
            "boundary repair",
            "segment boundaries",
            "split across",
            "cross chunk",
            "simplistic",
            "relationship logs",
            "records are omitted",
            "information to be skipped",
            "瑣碎",
            "漏掉",
        ),
    ),
    (
        "memory update semantics",
        (
            "dynamic time tracking",
            "this meeting",
            "one week ago",
            "meeting id",
            "meeting ids",
            "relative time",
            "temporal reference",
            "time tracking",
            "memory entry",
            "memory items are tracked",
            "item is mentioned again",
            "subsequent meeting discusses",
            "generate summaries and action items",
            "memory update process",
            "update function",
            "update memory nodes",
            "updating memory nodes",
            "correct memory node",
            "multiple memory nodes",
            "update methods",
            "update method",
            "時間軸",
            "會議id",
            "當前會議",
            "後續會議",
            "記憶條目",
            "更新相應的記憶",
        ),
    ),
    (
        "memory retrieval",
        (
            "retrieve phase",
            "retrieval phase",
            "retrieval component",
            "retrieval strategy",
            "recalling information",
            "distance for recalling",
            "recall distance",
            "memory retrieval",
            "can be recalled",
            "what can be recalled",
            "beyond three sessions",
            "more than three sessions",
            "取用",
            "檢索",
        ),
    ),
    (
        "memory evaluation strategy",
        (
            "memo",
            "locomo",
            "multi-hop",
            "multi hop",
            "llm-as-judge",
            "llm as judge",
            "benchmark",
            "evaluate",
            "evaluating",
            "evaluation",
            "precision",
            "recall",
            "ground truth",
            "gold",
            "standardized test",
            "standardized tests",
            "model performance",
            "proving its superiority",
            "prove its necessity",
        ),
    ),
    (
        "memory evidence anchoring",
        (
            "source link",
            "timestamp",
            "audio timestamp",
            "original recording",
            "evidence quote",
            "grounding",
            "source file",
        ),
    ),
    (
        "memory lifecycle",
        (
            "discard as l1",
            "discard-as-l1",
            "discard",
            "importance threshold",
            "importance score",
            "forgetting",
            "decay",
            "activation",
            "lifecycle",
            "unlinked",
            "skip l1",
        ),
    ),
    (
        "project demo strategy",
        (
            "minimum viable architecture",
            "full paper replication",
            "not full replication",
            "copying the whole paper",
            "added value",
            "demonstrates different agent behavior",
            "agent behavior",
            "human interaction",
            "perception",
            "demo strategy",
            "demonstration strategy",
            "memory-enhanced agent",
            "standard llm",
            "open-source code",
            "open source code",
            "highlight",
            "show the added value",
            "展示",
            "附加價值",
            "複製論文",
            "代理行為",
        ),
    ),
    (
        "stm ltm integration",
        (
            "short-term memory",
            "short term memory",
            "last three sessions",
            "stm",
            "ltm",
            "short-term and long-term",
            "short term and long term",
        ),
    ),
    (
        "memory processing architecture",
        (
            "hierarchical memory",
            "memory hierarchy",
            "bottom-up",
            "top-down",
            "top down",
            "parent-chain",
            "parent chain",
            "l1 to l2",
            "l1, l2",
            "l1 retrieval",
            "l2 context",
            "l3 context",
            "rag processing",
            "processing architecture",
            "memory architecture",
        ),
    ),
    (
        "l2 topic grouping",
        (
            "topic cluster",
            "l2 direction",
            "l2 topic",
            "topic grouping",
            "topic node",
            "topic-tree",
            "topic tree",
        ),
    ),
)


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_hash(data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _slug(text: str, *, fallback: str = "l2") -> str:
    slug = SLUG_RE.sub("-", text.lower()).strip("-")
    return slug or fallback


def _clean_text(text: str, *, limit: int = 220) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _obj_text(obj: dict[str, Any]) -> str:
    topics = obj.get("related_topics", [])
    topic_text = " ".join(str(topic) for topic in topics) if isinstance(topics, list) else ""
    return " ".join(
        part
        for part in (
            str(obj.get("content", "") or ""),
            str(obj.get("evidence", "") or ""),
            topic_text,
        )
        if part
    )


def _importance(obj: dict[str, Any]) -> float:
    try:
        return float(obj.get("importance", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _is_administrative(obj: dict[str, Any]) -> bool:
    text = _obj_text(obj).lower()
    return any(hint in text for hint in ADMINISTRATIVE_HINTS)


def _hint_matches(text: str, hint: str) -> bool:
    if not hint:
        return False
    start_boundary = r"(?<![a-z0-9])" if hint[0].isalnum() else ""
    end_boundary = r"(?![a-z0-9])" if hint[-1].isalnum() else ""
    return re.search(f"{start_boundary}{re.escape(hint)}{end_boundary}", text) is not None


def _concept_label(obj: dict[str, Any]) -> tuple[str | None, str]:
    topics = obj.get("related_topics", [])
    topic_text = " ".join(str(topic or "") for topic in topics) if isinstance(topics, list) else ""
    primary_text = " ".join(
        part
        for part in (
            str(obj.get("content", "") or ""),
            topic_text,
        )
        if part
    ).lower()
    for label, hints in CONCEPT_RULES:
        if any(_hint_matches(primary_text, hint) for hint in hints):
            return label, "concept_rule"

    evidence_text = str(obj.get("evidence", "") or "").lower()
    for label, hints in CONCEPT_RULES:
        if any(_hint_matches(evidence_text, hint) for hint in hints):
            return label, "evidence_concept_rule"
    return None, "no_concept"


def _topic_label_fallback(obj: dict[str, Any]) -> tuple[str | None, str]:
    topics = obj.get("related_topics", [])
    if not isinstance(topics, list):
        return None, "no_topic_fallback"
    for raw in topics:
        label = str(raw or "").replace("_", " ").replace("-", " ").strip().lower()
        if not label or label in GENERIC_LABELS or label in TYPE_LIKE_LABELS:
            continue
        canonical = RELATED_TOPIC_CANONICAL_LABELS.get(label)
        if not canonical:
            continue
        return canonical, "related_topic_fallback"
    return None, "no_topic_fallback"


def choose_l2_assignment(obj: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic L2 assignment or skip decision for one L1 object."""
    importance = _importance(obj)
    obj_type = str(obj.get("type", "") or "")
    if _is_administrative(obj):
        return {
            "action": "skip_l1",
            "reason": "administrative_or_local_context",
            "review_required": importance >= 0.7,
            "confidence": 0.78,
        }

    label, reason = _concept_label(obj)
    if label is None:
        label, reason = _topic_label_fallback(obj)

    if label is None:
        return {
            "action": "skip_l1",
            "reason": "no_durable_l2_concept",
            "review_required": importance >= 0.7,
            "confidence": 0.64,
        }

    if reason == "related_topic_fallback" and importance < RELATED_TOPIC_FALLBACK_MIN_IMPORTANCE:
        return {
            "action": "skip_l1",
            "reason": "related_topic_below_l2_threshold",
            "review_required": False,
            "confidence": 0.68,
        }

    durable_type = obj_type in {
        "decision",
        "action_item",
        "todo",
        "open_issue",
        "open_question",
        "approach_change",
        "method_change",
        "proposal",
        "finding",
        "result",
        "argument",
    }
    if importance < 0.55 and not durable_type:
        return {
            "action": "skip_l1",
            "reason": "below_l2_importance_threshold",
            "review_required": False,
            "confidence": 0.7,
        }

    return {
        "action": "assign_l2",
        "l2_label": label,
        "reason": reason,
        "review_required": False,
        "confidence": round(min(0.95, 0.62 + importance * 0.28), 3),
    }


def empty_l2_view(*, source_tree_hash: str = "") -> dict[str, Any]:
    return {
        "schema_version": L2_VIEW_SCHEMA_VERSION,
        "generated_at_utc": "",
        "source": "share_mem",
        "source_tree_hash": source_tree_hash,
        "l2_nodes": [],
    }


def load_l2_view(root: Path | str) -> dict[str, Any]:
    path = Path(root) / L2_VIEW_FILE_NAME
    if not path.exists():
        return empty_l2_view()
    data = _load_json(path)
    if not isinstance(data, dict):
        raise RuntimeError(f"L2 view must be a JSON object: {path}")
    return data


def load_l2_index(root: Path | str) -> dict[str, Any]:
    path = Path(root) / L2_INDEX_FILE_NAME
    if not path.exists():
        return {}
    data = _load_json(path)
    if not isinstance(data, dict):
        raise RuntimeError(f"L2 index must be a JSON object: {path}")
    return data


def load_share_mem_l1_tree(share_mem_root: Path | str) -> dict[str, Any]:
    root = Path(share_mem_root)
    tree = load_share_tree(root)
    if list(iter_meetings(tree)):
        return tree

    meetings_dir = root / "meetings"
    meetings: list[dict[str, Any]] = []
    if meetings_dir.exists():
        for path in sorted(meetings_dir.glob("*.json")):
            data = _load_json(path)
            if isinstance(data, dict):
                meetings.append(data)
    return normalize_share_tree(
        {
            "tree_version": 0,
            "last_updated_utc": "",
            "project_profile": {},
            "phases": [],
            "meetings": meetings,
        }
    )


def clean_l2_outputs(output_root: Path | str) -> None:
    root = Path(output_root)
    for file_name in (L2_VIEW_FILE_NAME, L2_INDEX_FILE_NAME, L2_MANIFEST_FILE_NAME, L2_UNLINKED_FILE_NAME):
        path = root / file_name
        if path.exists():
            path.unlink()
    for dir_name in (L2_UPDATES_DIR_NAME, L2_RESEARCH_LOGS_DIR_NAME, "validation"):
        path = root / dir_name
        if path.exists():
            shutil.rmtree(path)


def _event_id(meeting_id: str, index: int) -> str:
    return f"L2E-{meeting_id}-{index:03d}"


def _build_l2_node(label: str, linked: list[dict[str, Any]]) -> dict[str, Any]:
    meeting_ids = sorted({str(item["meeting"].get("meeting_id", "") or "") for item in linked})
    timeline = [
        {
            "meeting_id": str(item["meeting"].get("meeting_id", "") or ""),
            "meeting_date": str(item["meeting"].get("meeting_date", "") or ""),
            "obj_id": str(item["obj"].get("obj_id", "") or ""),
            "summary": _clean_text(item["obj"].get("content", ""), limit=180),
        }
        for item in linked
    ]
    latest = timeline[-1]["summary"] if timeline else ""
    avg_confidence = (
        sum(float(item["assignment"].get("confidence", 0.0)) for item in linked) / len(linked)
        if linked
        else 0.0
    )
    return {
        "l2_id": f"L2-{_slug(label)}",
        "label": label,
        "source": "long_term_l2",
        "current_state": (
            f"This L2 direction has {len(linked)} linked L1 evidence objects across "
            f"{len(meeting_ids)} meeting(s). Latest evidence: {latest}"
        ),
        "timeline_digest": timeline,
        "linked_obj_ids": [str(item["obj"].get("obj_id", "") or "") for item in linked],
        "meeting_ids": meeting_ids,
        "event_count": len(linked),
        "confidence": round(avg_confidence, 3),
        "last_updated_meeting_id": str(linked[-1]["meeting"].get("meeting_id", "") or "") if linked else "",
    }


def _build_outputs(
    *,
    tree: dict[str, Any],
    share_mem_root: Path,
    output_root: Path,
    mode: str,
) -> dict[str, Any]:
    source_tree_hash = stable_hash(tree)
    linked_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    l2_index: dict[str, dict[str, Any]] = {}
    unlinked_objects: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []
    updates_by_meeting: dict[str, dict[str, Any]] = {}
    source_l1_count = 0

    for meeting in iter_meetings(tree):
        meeting_id = str(meeting.get("meeting_id", "") or "")
        meeting_events: list[dict[str, Any]] = []
        for ordinal, obj in enumerate(meeting.get("memory_objects", []), start=1):
            if not isinstance(obj, dict) or not str(obj.get("obj_id", "") or "").strip():
                continue
            source_l1_count += 1
            obj_id = str(obj.get("obj_id", "") or "")
            assignment = choose_l2_assignment(obj)
            event = {
                "event_id": _event_id(meeting_id, ordinal),
                "meeting_id": meeting_id,
                "obj_id": obj_id,
                "source_l1_type": str(obj.get("type", "") or ""),
                "importance": _importance(obj),
                "action": assignment["action"],
                "reason": assignment.get("reason", ""),
                "confidence": assignment.get("confidence", 0.0),
            }
            if assignment["action"] == "assign_l2":
                label = str(assignment["l2_label"])
                l2_id = f"L2-{_slug(label)}"
                action = "assign_existing" if linked_by_label[label] else "new_l2"
                event.update(
                    {
                        "action": action,
                        "l2_id": l2_id,
                        "l2_label": label,
                    }
                )
                linked_by_label[label].append(
                    {
                        "meeting": meeting,
                        "obj": obj,
                        "assignment": assignment,
                        "event_id": event["event_id"],
                    }
                )
                l2_index[obj_id] = {
                    "obj_id": obj_id,
                    "meeting_id": meeting_id,
                    "meeting_date": str(meeting.get("meeting_date", "") or ""),
                    "l2_id": l2_id,
                    "l2_label": label,
                    "source": "long_term_l2",
                    "event_id": event["event_id"],
                    "confidence": assignment.get("confidence", 0.0),
                    "assignment_reason": assignment.get("reason", ""),
                }
            else:
                skipped = {
                    "obj_id": obj_id,
                    "meeting_id": meeting_id,
                    "meeting_date": str(meeting.get("meeting_date", "") or ""),
                    "type": str(obj.get("type", "") or ""),
                    "importance": _importance(obj),
                    "content": _clean_text(obj.get("content", ""), limit=220),
                    "reason": assignment.get("reason", ""),
                    "review_required": bool(assignment.get("review_required", False)),
                }
                unlinked_objects.append(skipped)
                if skipped["review_required"]:
                    review_queue.append(skipped)
            meeting_events.append(event)
        updates_by_meeting[meeting_id] = {
            "schema_version": L2_VIEW_SCHEMA_VERSION,
            "meeting_id": meeting_id,
            "meeting_date": str(meeting.get("meeting_date", "") or ""),
            "source_hash": stable_hash(meeting),
            "mode": mode,
            "l2_events": meeting_events,
        }

    nodes = [_build_l2_node(label, linked) for label, linked in sorted(linked_by_label.items())]
    l2_view = {
        "schema_version": L2_VIEW_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "source": "share_mem",
        "share_mem_root": str(share_mem_root.resolve()),
        "source_tree_hash": source_tree_hash,
        "mode": mode,
        "l2_nodes": nodes,
    }
    unlinked_report = {
        "schema_version": L2_VIEW_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "source_tree_hash": source_tree_hash,
        "unlinked_count": len(unlinked_objects),
        "review_queue_count": len(review_queue),
        "unlinked_objects": unlinked_objects,
        "review_queue": review_queue,
    }
    manifest = {
        "schema_version": L2_VIEW_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "share_mem_root": str(share_mem_root.resolve()),
        "output_root": str(output_root.resolve()),
        "mode": mode,
        "source_tree_hash": source_tree_hash,
        "meeting_count": len(list(iter_meetings(tree))),
        "source_l1_count": source_l1_count,
        "linked_l1_count": len(l2_index),
        "unlinked_l1_count": len(unlinked_objects),
        "review_queue_count": len(review_queue),
        "l2_count": len(nodes),
        "l2_view_path": str((output_root / L2_VIEW_FILE_NAME).resolve()),
        "l2_index_path": str((output_root / L2_INDEX_FILE_NAME).resolve()),
        "unlinked_l1_report_path": str((output_root / L2_UNLINKED_FILE_NAME).resolve()),
    }
    return {
        "l2_view": l2_view,
        "l2_index": dict(sorted(l2_index.items())),
        "updates_by_meeting": updates_by_meeting,
        "unlinked_report": unlinked_report,
        "manifest": manifest,
    }


def build_l2_view_outputs(
    *,
    share_mem_root: Path | str = REPO_ROOT / "share_mem",
    output_root: Path | str = REPO_ROOT / "long_term" / "l2",
    mode: str = "hybrid",
    model: str | None = None,
    clean: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    del model  # Hybrid API assignment is intentionally not used in the first L2 builder.
    if mode not in SUPPORTED_L2_MODES:
        raise ValueError(f"Unsupported L2 mode: {mode}")
    share_root = Path(share_mem_root)
    out_root = Path(output_root)
    tree = load_share_mem_l1_tree(share_root)
    if clean and not dry_run:
        clean_l2_outputs(out_root)

    outputs = _build_outputs(
        tree=tree,
        share_mem_root=share_root,
        output_root=out_root,
        mode=mode,
    )
    if dry_run:
        return outputs["manifest"]

    _write_json(out_root / L2_VIEW_FILE_NAME, outputs["l2_view"])
    _write_json(out_root / L2_INDEX_FILE_NAME, outputs["l2_index"])
    _write_json(out_root / L2_UNLINKED_FILE_NAME, outputs["unlinked_report"])
    for meeting_id, update in sorted(outputs["updates_by_meeting"].items()):
        _write_json(out_root / L2_UPDATES_DIR_NAME / f"{meeting_id}.json", update)
    _write_json(out_root / L2_MANIFEST_FILE_NAME, outputs["manifest"])
    return outputs["manifest"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an L2 view from canonical share_mem L1 evidence."
    )
    parser.add_argument(
        "--share-mem-root",
        default=str(REPO_ROOT / "share_mem"),
        help="Root containing share_mem tree.json and meetings/.",
    )
    parser.add_argument(
        "--output-root",
        default=str(REPO_ROOT / "long_term" / "l2"),
        help="Output root for generated L2 view artifacts.",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(SUPPORTED_L2_MODES),
        default="hybrid",
        help="Assignment mode. The first implementation uses deterministic assignment for both modes.",
    )
    parser.add_argument("--model", default=None, help="Reserved for future Gemini-assisted assignment.")
    parser.add_argument("--clean", action="store_true", help="Clean generated L2 outputs.")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without writing.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    manifest = build_l2_view_outputs(
        share_mem_root=args.share_mem_root,
        output_root=args.output_root,
        mode=args.mode,
        model=args.model,
        clean=bool(args.clean),
        dry_run=bool(args.dry_run),
    )
    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    print(
        "[long_term] L2 view refreshed: "
        f"{manifest['l2_count']} L2 nodes, "
        f"{manifest['linked_l1_count']} linked L1, "
        f"{manifest['unlinked_l1_count']} unlinked L1"
    )
    print(f"L2 view: {manifest['l2_view_path']}")


if __name__ == "__main__":
    main()
