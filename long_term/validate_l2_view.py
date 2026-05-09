"""Validate the active long_term L2 view against canonical share_mem L1 evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_l2_view import (
    GENERIC_LABELS,
    L2_INDEX_FILE_NAME,
    L2_UNLINKED_FILE_NAME,
    L2_VIEW_FILE_NAME,
    TYPE_LIKE_LABELS,
    load_l2_index,
    load_l2_view,
)
from share_mem.store import build_l1_index, load_share_tree
from validate_l3_view import validate_l3_view_outputs

EXPECTED_L2_ASSIGNMENTS = {
    "L1-0307-005": "memory update semantics",
    "L1-0307-006": "memory update semantics",
    "L1-0307-012": "research methodology",
    "L1-0307-047": "data fragmentation",
    "L1-0318-002": "memory evaluation strategy",
    "L1-0318-003": "agentic pipeline control",
    "L1-0325-002": "memory evidence anchoring",
    "L1-0325-003": "memory evidence anchoring",
    "L1-0325-004": "memory evidence anchoring",
    "L1-0325-018": "memory evidence anchoring",
    "L1-0325-019": "memory evidence anchoring",
    "L1-0325-061": "memory retrieval",
    "L1-0408-004": "dataset selection",
    "L1-0408-017": "transcript segmentation and idea-unit coverage",
    "L1-0408-030": "memory retrieval",
    "L1-0408-036": "stm ltm integration",
    "L1-0408-041": "memory retrieval",
    "L1-0408-043": "memory retrieval",
    "L1-0408-052": "transcript segmentation and idea-unit coverage",
    "L1-0408-054": "memory lifecycle",
    "L1-0408-057": "memory retrieval",
    "L1-0422-015": "transcript segmentation and idea-unit coverage",
    "L1-0422-046": "stm ltm integration",
    "L1-0422-053": "memory lifecycle",
    "L1-0429-004": "dataset selection",
    "L1-0429-025": "transcript segmentation and idea-unit coverage",
    "L1-0429-032": "l2 topic grouping",
    "L1-0429-033": "transcript segmentation and idea-unit coverage",
    "L1-0429-037": "transcript segmentation and idea-unit coverage",
    "L1-0429-057": "memory evaluation strategy",
    "L1-0429-058": "memory evaluation strategy",
    "L1-0429-059": "dataset selection",
    "L1-0429-101": "transcript segmentation and idea-unit coverage",
    "L1-0429-107": "agentic pipeline control",
    "L1-0429-127": "transcript segmentation and idea-unit coverage",
    "L1-0429-139": "agentic pipeline control",
    "L1-0429-145": "agentic pipeline control",
    "L1-0506-013": "prompt design and instruction quality",
    "L1-0506-006": "transcript segmentation and idea-unit coverage",
    "L1-0506-009": "transcript segmentation and idea-unit coverage",
    "L1-0506-024": "pipeline observability and validation",
    "L1-0506-028": "agentic pipeline control",
    "L1-0506-029": "l2 topic grouping",
    "L1-0506-032": "l2 topic grouping",
    "L1-0506-036": "memory lifecycle",
    "L1-0506-038": "memory lifecycle",
    "L1-0506-040": "memory lifecycle",
    "L1-0506-041": "memory lifecycle",
    "L1-0506-042": "memory lifecycle",
}

EXPECTED_L2_LABEL_ANCHORS = {
    "agentic pipeline control": (
        "agent",
        "manager",
        "tool calling",
        "code-driven",
        "control flow",
        "main code",
        "llm-controlled",
    ),
    "data fragmentation": (
        "fragment",
        "chunk",
        "boundary",
        "split",
        "sentence",
    ),
    "dataset selection": (
        "dataset",
        "benchmark",
        "locomo",
        "memo",
        "mirix",
        "ground truth",
    ),
    "l2 topic grouping": (
        "l2",
        "topic",
        "topic-tree",
        "topic tree",
        "cluster",
        "grouping",
    ),
    "memory evaluation strategy": (
        "evaluation",
        "benchmark",
        "llm-as-judge",
        "llm as judge",
        "locomo",
        "memo",
        "multi-hop",
        "metric",
    ),
    "memory evidence anchoring": (
        "evidence",
        "grounding",
        "quote",
        "timestamp",
        "anchor",
        "source",
    ),
    "memory lifecycle": (
        "activation",
        "decay",
        "recency",
        "fade",
        "inactive",
        "discard",
        "importance threshold",
    ),
    "memory processing architecture": (
        "hierarchical",
        "hierarchy",
        "bottom-up",
        "top-down",
        "l1",
        "l2",
        "l3",
        "rag",
        "parent",
        "topic-based",
        "memory architecture",
    ),
    "memory retrieval": (
        "retrieval",
        "retrieve",
        "recall",
        "semantic search",
        "query",
        "prompt context",
    ),
    "memory update semantics": (
        "update",
        "supersede",
        "append",
        "evolution",
        "timestamp",
        "same topic",
    ),
    "pipeline observability and validation": (
        "log",
        "api call",
        "validation",
        "validator",
        "debug",
        "trace",
        "inspection",
        "visualization",
    ),
    "prompt design and instruction quality": (
        "prompt",
        "instruction",
        "jargon",
        "repair",
        "agent understand",
        "self-contained",
    ),
    "project demo strategy": (
        "demo",
        "poster",
        "presentation",
        "mvp",
        "minimum viable",
    ),
    "research methodology": (
        "methodology",
        "research",
        "paper",
        "experiment",
        "replication",
        "study",
    ),
    "stm ltm integration": (
        "short-term",
        "short term",
        "stm",
        "long-term",
        "long term",
        "ltm",
        "share_mem",
    ),
    "transcript segmentation and idea-unit coverage": (
        "segment",
        "segmentation",
        "idea unit",
        "chunk",
        "line",
        "coverage",
        "gap",
    ),
}

EXPECTED_L2_OBJECT_ANCHORS = {
    "L1-0318-003": (
        "shared blackboard",
        "blackboard architecture",
        "error propagation",
        "global context",
    ),
    "L1-0429-032": (
        "objects",
        "issues",
        "item tracking",
        "importance increases",
        "two-layer",
    ),
    "L1-0429-057": (
        "forgetting",
        "inactive",
        "fade",
        "long-term information",
        "retrievable state",
    ),
    "L1-0429-059": (
        "data augmentation",
        "dataset acquisition",
        "data shortage",
        "other students",
        "longitudinal dataset",
    ),
    "L1-0429-025": (
        "fixed chunk size",
        "approximately 20 lines",
        "20 line",
        "20行",
        "文本區塊",
    ),
    "L1-0429-033": (
        "20行",
        "文本區塊",
        "固定",
        "非動態",
    ),
    "L1-0429-101": (
        "40到80行",
        "重疊",
        "控制權",
        "文本分塊",
    ),
    "L1-0506-028": (
        "duplicate candidate",
        "duplicate candidates",
        "same idea unit",
        "同一個 idea unit",
        "重複的 candidate",
    ),
}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _issue(
    code: str,
    severity: str,
    message: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        **details,
    }


def _view_link_map(l2_view: dict[str, Any]) -> dict[str, set[str]]:
    links: dict[str, set[str]] = {}
    for node in l2_view.get("l2_nodes", []):
        if not isinstance(node, dict):
            continue
        l2_id = str(node.get("l2_id", "") or "")
        links[l2_id] = {str(obj_id) for obj_id in node.get("linked_obj_ids", [])}
    return links


def _materialized_l3_source_l2_ids(l3_view: dict[str, Any]) -> set[str]:
    source_ids: set[str] = set()
    nodes = l3_view.get("l3_nodes", [])
    if not isinstance(nodes, list):
        return source_ids
    for node in nodes:
        if not isinstance(node, dict):
            continue
        source_l2_id = str(node.get("promoted_from_l2_id", "") or "").strip()
        child_nodes = node.get("child_l2_nodes", [])
        if source_l2_id and isinstance(child_nodes, list) and len(child_nodes) >= 2:
            source_ids.add(source_l2_id)
    return source_ids


def _validate_l2_nodes(
    l2_view: dict[str, Any],
    l2_index: dict[str, Any],
    *,
    materialized_l3_source_l2_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    indexed_obj_ids = set(l2_index)
    promoted_l2_ids = materialized_l3_source_l2_ids or set()
    seen_ids: set[str] = set()
    for node in l2_view.get("l2_nodes", []):
        if not isinstance(node, dict):
            continue
        l2_id = str(node.get("l2_id", "") or "")
        label = str(node.get("label", "") or "").strip().lower()
        if not l2_id:
            issues.append(_issue("missing_l2_id", "severe", "L2 node is missing l2_id."))
        if l2_id in seen_ids:
            issues.append(_issue("duplicate_l2_id", "severe", "Duplicate L2 node id.", l2_id=l2_id))
        seen_ids.add(l2_id)
        if not label:
            issues.append(_issue("missing_l2_label", "severe", "L2 node is missing a label.", l2_id=l2_id))
        if label in GENERIC_LABELS or label in TYPE_LIKE_LABELS:
            issues.append(
                _issue(
                    "generic_l2_label",
                    "severe",
                    "L2 label is too generic or type-like.",
                    l2_id=l2_id,
                    label=label,
                )
            )
        linked_ids = [str(obj_id) for obj_id in node.get("linked_obj_ids", [])]
        for obj_id in linked_ids:
            if obj_id not in indexed_obj_ids:
                issues.append(
                    _issue(
                        "linked_obj_missing_from_index",
                        "severe",
                        "L2 node links an object that is absent from l2_index.",
                        l2_id=l2_id,
                        obj_id=obj_id,
                    )
                )
            else:
                indexed_l2_id = str(l2_index[obj_id].get("l2_id", "") or "")
                if indexed_l2_id != l2_id:
                    issues.append(
                        _issue(
                            "linked_obj_index_l2_mismatch",
                            "severe",
                            "L2 node link and l2_index disagree on the object's L2 id.",
                            l2_id=l2_id,
                            indexed_l2_id=indexed_l2_id,
                            obj_id=obj_id,
                        )
                    )
        if len(linked_ids) > 60 and l2_id not in promoted_l2_ids:
            issues.append(
                _issue(
                    "large_l2_topic",
                    "warning",
                    "L2 node has many linked L1 objects and should be manually reviewed.",
                    l2_id=l2_id,
                    label=label,
                    linked_count=len(linked_ids),
                )
            )
    return issues


def _validate_l2_index(l2_view: dict[str, Any], l2_index: dict[str, Any], l1_index: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    view_links = _view_link_map(l2_view)
    l2_ids = set(view_links)
    for obj_id, entry in l2_index.items():
        if obj_id not in l1_index:
            issues.append(
                _issue(
                    "index_obj_missing_from_share_mem",
                    "severe",
                    "l2_index references an obj_id absent from share_mem.",
                    obj_id=obj_id,
                )
            )
        l2_id = str(entry.get("l2_id", "") or "")
        if l2_id not in l2_ids:
            issues.append(
                _issue(
                    "index_l2_missing_from_view",
                    "severe",
                    "l2_index references an L2 id absent from l2_view.",
                    obj_id=obj_id,
                    l2_id=l2_id,
                )
            )
        elif obj_id not in view_links[l2_id]:
            issues.append(
                _issue(
                    "index_obj_missing_from_view_node",
                    "severe",
                    "l2_index references an object absent from its L2 node linked_obj_ids.",
                    obj_id=obj_id,
                    l2_id=l2_id,
                )
            )
    return issues


def _validate_unlinked(
    unlinked_report: dict[str, Any],
    l2_index: dict[str, Any],
    l1_index: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    unlinked_items = [
        item for item in unlinked_report.get("unlinked_objects", []) if isinstance(item, dict)
    ]
    unlinked_ids = {str(item.get("obj_id", "") or "") for item in unlinked_items}
    indexed_ids = set(l2_index)
    source_ids = set(l1_index)

    for obj_id in sorted(unlinked_ids & indexed_ids):
        issues.append(
            _issue(
                "unlinked_obj_also_indexed",
                "severe",
                "An L1 object appears in both unlinked_objects and l2_index.",
                obj_id=obj_id,
                l2_id=str(l2_index[obj_id].get("l2_id", "") or ""),
            )
        )

    missing_ids = source_ids - indexed_ids - unlinked_ids
    for obj_id in sorted(missing_ids):
        issues.append(
            _issue(
                "l1_missing_from_l2_outputs",
                "severe",
                "A share_mem L1 object is absent from both l2_index and unlinked_objects.",
                obj_id=obj_id,
            )
        )

    extra_unlinked_ids = unlinked_ids - source_ids
    for obj_id in sorted(extra_unlinked_ids):
        issues.append(
            _issue(
                "unlinked_obj_missing_from_share_mem",
                "severe",
                "unlinked_objects references an obj_id absent from share_mem.",
                obj_id=obj_id,
            )
        )

    for item in unlinked_items:
        if not isinstance(item, dict):
            continue
        try:
            importance = float(item.get("importance", 0.0))
        except (TypeError, ValueError):
            importance = 0.0
        reason = str(item.get("reason", "") or "")
        if reason == "administrative_or_local_context":
            continue
        if importance >= 0.7 or item.get("review_required"):
            issues.append(
                _issue(
                    "high_importance_unlinked",
                    "warning",
                    "High-importance or review-required L1 is not linked to any L2.",
                    obj_id=str(item.get("obj_id", "") or ""),
                    meeting_id=str(item.get("meeting_id", "") or ""),
                    importance=importance,
                    reason=reason,
                )
            )

    review_ids = {
        str(item.get("obj_id", "") or "")
        for item in unlinked_report.get("review_queue", [])
        if isinstance(item, dict)
    }
    stale_review_ids = review_ids - unlinked_ids
    for obj_id in sorted(stale_review_ids):
        issues.append(
            _issue(
                "review_queue_obj_missing_from_unlinked",
                "warning",
                "review_queue references an object that is not present in unlinked_objects.",
                obj_id=obj_id,
            )
        )
    return issues


def _matches_expected_assignment_anchor(
    obj_id: str,
    obj: dict[str, Any],
    expected_label: str,
) -> bool:
    """Return whether an obj_id-specific expected topic still applies.

    L1 ids are stable within one generated tree, but live re-extraction can
    assign a different semantic object to the same numeric id. The expected
    assignment gate is therefore content-scoped: it should catch regressions
    for the known canonical object, not punish a new object that reused the id.
    """

    anchors = EXPECTED_L2_OBJECT_ANCHORS.get(obj_id) or EXPECTED_L2_LABEL_ANCHORS.get(
        expected_label
    )
    if not anchors:
        return True
    topics = obj.get("topics", [])
    topic_text = " ".join(str(topic) for topic in topics) if isinstance(topics, list) else ""
    text = " ".join(
        [
            str(obj.get("content", "") or ""),
            topic_text,
        ]
    ).lower()
    normalized = text.replace("_", " ").replace("-", " ")
    return any(anchor in normalized for anchor in anchors)


def _validate_expected_assignments(l2_index: dict[str, Any], l1_index: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for obj_id, expected_label in EXPECTED_L2_ASSIGNMENTS.items():
        if obj_id not in l1_index:
            continue
        obj = l1_index[obj_id]
        if not _matches_expected_assignment_anchor(obj_id, obj, expected_label):
            continue
        entry = l2_index.get(obj_id)
        actual_label = str(entry.get("l2_label", "") or "") if isinstance(entry, dict) else ""
        if actual_label != expected_label:
            issues.append(
                _issue(
                    "expected_l2_assignment_mismatch",
                    "severe",
                    "Known L2 topic quality regression does not match the expected assignment.",
                    obj_id=obj_id,
                    expected_l2_label=expected_label,
                    actual_l2_label=actual_label or "<unlinked>",
                )
            )
    return issues


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# L2 Validation Report",
        "",
        f"- L2 count: {report['l2_count']}",
        f"- Linked L1 count: {report['linked_l1_count']}",
        f"- Issue count: {report['issue_count']}",
        f"- Severe count: {report['severe_count']}",
        f"- Warning count: {report['warning_count']}",
        "",
        "## Issues",
    ]
    if not report["issues"]:
        lines.append("")
        lines.append("No issues.")
    else:
        for issue in report["issues"]:
            lines.append(
                f"- [{issue['severity']}] {issue['code']}: {issue['message']}"
            )
    lines.append("")
    return "\n".join(lines)


def validate_l2_view_outputs(
    *,
    share_mem_root: Path | str = REPO_ROOT / "share_mem",
    root: Path | str = REPO_ROOT / "long_term" / "l2",
    out: Path | str | None = None,
) -> dict[str, Any]:
    share_root = Path(share_mem_root)
    l2_root = Path(root)
    out_root = Path(out) if out is not None else l2_root / "validation"
    share_tree = load_share_tree(share_root)
    l1_index = build_l1_index(share_tree)
    l2_view = load_l2_view(l2_root)
    l2_index = load_l2_index(l2_root)
    unlinked_report = _load_json(l2_root / L2_UNLINKED_FILE_NAME)
    l3_view = _load_json(l2_root.parent / "l3" / "l3_view.json")
    materialized_l3_source_l2_ids = _materialized_l3_source_l2_ids(
        l3_view if isinstance(l3_view, dict) else {}
    )

    issues = [
        *_validate_l2_nodes(
            l2_view,
            l2_index,
            materialized_l3_source_l2_ids=materialized_l3_source_l2_ids,
        ),
        *_validate_l2_index(l2_view, l2_index, l1_index),
        *_validate_unlinked(
            unlinked_report if isinstance(unlinked_report, dict) else {},
            l2_index,
            l1_index,
        ),
        *_validate_expected_assignments(l2_index, l1_index),
    ]
    manual_queue = [
        issue
        for issue in issues
        if issue["code"] in {
            "expected_l2_assignment_mismatch",
            "high_importance_unlinked",
            "large_l2_topic",
            "generic_l2_label",
        }
    ]
    severe_count = sum(1 for issue in issues if issue["severity"] == "severe")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    report = {
        "schema_version": 1,
        "share_mem_root": str(share_root.resolve()),
        "l2_root": str(l2_root.resolve()),
        "l2_view_path": str((l2_root / L2_VIEW_FILE_NAME).resolve()),
        "l2_index_path": str((l2_root / L2_INDEX_FILE_NAME).resolve()),
        "l2_count": len(l2_view.get("l2_nodes", [])),
        "linked_l1_count": len(l2_index),
        "issue_count": len(issues),
        "severe_count": severe_count,
        "warning_count": warning_count,
        "issues": issues,
        "manual_review_count": len(manual_queue),
        "resolved_large_l2_promotion_count": len(materialized_l3_source_l2_ids),
    }
    _write_json(out_root / "l2_validation_report.json", report)
    _write_json(out_root / "manual_l2_review_queue.json", manual_queue)
    (out_root / "l2_validation_report.md").write_text(_markdown_report(report), encoding="utf-8")
    validate_l3_view_outputs(
        share_mem_root=share_root,
        l2_root=l2_root,
        l3_root=l2_root.parent / "l3",
        out=l2_root.parent / "l3" / "validation",
    )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a generated L2 view against canonical share_mem L1 evidence."
    )
    parser.add_argument(
        "--share-mem-root",
        default=str(REPO_ROOT / "share_mem"),
        help="Root containing canonical share_mem L1 outputs.",
    )
    parser.add_argument(
        "--root",
        default=str(REPO_ROOT / "long_term" / "l2"),
        help="Root containing generated L2 view artifacts.",
    )
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "long_term" / "l2" / "validation"),
        help="Validation output directory.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    report = validate_l2_view_outputs(
        share_mem_root=args.share_mem_root,
        root=args.root,
        out=args.out,
    )
    print(
        "[long_term] L2 validation complete: "
        f"{report['severe_count']} severe, {report['warning_count']} warnings"
    )
    print(f"Report: {Path(args.out) / 'l2_validation_report.json'}")
    if report["severe_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
