from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .store import iter_l1_objects, load_share_tree
    from .topic_view import (
        OVER_BROAD_TOPIC_LABELS,
        TOPIC_INDEX_FILE_NAME,
        TOPIC_TREE_FILE_NAME,
        TYPE_LIKE_TOPIC_LABELS,
        _concept_keys_for_obj,
        load_topic_index,
        load_topic_tree,
        normalize_topic_label,
    )
except ImportError:  # pragma: no cover - direct script execution fallback
    from store import iter_l1_objects, load_share_tree  # type: ignore
    from topic_view import (  # type: ignore
        OVER_BROAD_TOPIC_LABELS,
        TOPIC_INDEX_FILE_NAME,
        TOPIC_TREE_FILE_NAME,
        TYPE_LIKE_TOPIC_LABELS,
        _concept_keys_for_obj,
        load_topic_index,
        load_topic_tree,
        normalize_topic_label,
    )


DEFAULT_EXPECTED_LINKS = [
    {
        "source_obj_id": "L1-0429-025",
        "target_obj_id": "L1-0506-009",
        "topic_path": ["memory", "memory processing architecture"],
        "source_required_markers": ["hierarchical", "rag"],
        "target_required_markers": ["top-down", "bottom-up"],
    }
]

EXPECTED_CONCEPT_TOPIC_PATHS = {
    "data fragmentation": ["data fragmentation", "data fragmentation"],
    "memory processing architecture": ["memory", "memory processing architecture"],
}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _topic_nodes(topic_tree: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for root in topic_tree.get("topic_roots", []):
        if not isinstance(root, dict):
            continue
        for child in root.get("children", []):
            if isinstance(child, dict):
                rows.append((root, child))
    return rows


def _issue(
    *,
    code: str,
    severity: str,
    message: str,
    root_label: str = "",
    topic_label: str = "",
    topic_id: str = "",
    obj_id: str = "",
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "root_label": root_label,
        "topic_label": topic_label,
        "topic_id": topic_id,
        "obj_id": obj_id,
    }


def _validate_labels(
    topic_tree: dict[str, Any],
    *,
    max_topic_event_count: int,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    banned = {normalize_topic_label(label) for label in TYPE_LIKE_TOPIC_LABELS}
    over_broad = {normalize_topic_label(label) for label in OVER_BROAD_TOPIC_LABELS}
    for root, child in _topic_nodes(topic_tree):
        root_label = str(root.get("label", "") or "")
        topic_label = str(child.get("label", "") or "")
        normalized_root = normalize_topic_label(root_label)
        normalized_topic = normalize_topic_label(topic_label)
        topic_id = str(child.get("topic_id", "") or "")
        event_count = len([item for item in child.get("event_ids", []) if str(item).strip()])
        if normalized_root in banned or normalized_topic in banned:
            issues.append(
                _issue(
                    code="banned_topic_label",
                    severity="severe",
                    message="Topic labels must describe long-running subjects, not L1 types.",
                    root_label=root_label,
                    topic_label=topic_label,
                    topic_id=topic_id,
                )
            )
        if normalized_topic in over_broad and event_count > max_topic_event_count:
            issues.append(
                _issue(
                    code="over_broad_topic",
                    severity="severe",
                    message="Over-broad memory topic has too many events and should split into concrete lines.",
                    root_label=root_label,
                    topic_label=topic_label,
                    topic_id=topic_id,
                )
            )
        elif event_count > max_topic_event_count:
            issues.append(
                _issue(
                    code="large_topic",
                    severity="warning",
                    message="Large topic should be manually reviewed for accidental merging.",
                    root_label=root_label,
                    topic_label=topic_label,
                    topic_id=topic_id,
                )
            )
    return issues


def _validate_expected_links(
    topic_index: dict[str, Any],
    obj_by_id: dict[str, dict[str, Any]],
    expected_links: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for expected in expected_links:
        source_obj_id = str(expected.get("source_obj_id", "") or "")
        target_obj_id = str(expected.get("target_obj_id", "") or "")
        if source_obj_id not in topic_index or target_obj_id not in topic_index:
            continue
        source_obj = obj_by_id.get(source_obj_id, {})
        target_obj = obj_by_id.get(target_obj_id, {})
        source_markers = [str(item) for item in expected.get("source_required_markers", [])]
        target_markers = [str(item) for item in expected.get("target_required_markers", [])]
        if source_markers and not _object_has_markers(source_obj, source_markers):
            continue
        if target_markers and not _object_has_markers(target_obj, target_markers):
            continue
        source = topic_index[source_obj_id]
        target = topic_index[target_obj_id]
        if source.get("topic_id") != target.get("topic_id"):
            issues.append(
                _issue(
                    code="expected_link_missing",
                    severity="severe",
                    message=f"{source_obj_id} and {target_obj_id} should resolve to the same topic.",
                    obj_id=source_obj_id,
                    topic_id=str(source.get("topic_id", "") or ""),
                    topic_label=" / ".join(str(item) for item in source.get("topic_path", [])),
                )
            )
            continue
        expected_path = expected.get("topic_path", [])
        if expected_path and list(source.get("topic_path", [])) != list(expected_path):
            issues.append(
                _issue(
                    code="expected_topic_path_mismatch",
                    severity="severe",
                    message=f"{source_obj_id} is linked, but not under the expected topic path.",
                    obj_id=source_obj_id,
                    topic_id=str(source.get("topic_id", "") or ""),
                    topic_label=" / ".join(str(item) for item in source.get("topic_path", [])),
                )
            )
    return issues


def _object_text(obj: dict[str, Any]) -> str:
    raw_topics = obj.get("related_topics", [])
    topics = " ".join(str(item) for item in raw_topics) if isinstance(raw_topics, list) else ""
    return " ".join(
        [
            str(obj.get("content", "") or ""),
            str(obj.get("evidence", "") or ""),
            topics,
        ]
    ).lower()


def _object_has_markers(obj: dict[str, Any], markers: list[str]) -> bool:
    text = _object_text(obj)
    return all(str(marker or "").lower() in text for marker in markers)


def _normalized_path(path: Any) -> list[str]:
    return [normalize_topic_label(str(item)) for item in path if str(item).strip()]


def _validate_concept_paths(
    topic_index: dict[str, Any],
    obj_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for obj_id, obj in sorted(obj_by_id.items()):
        if obj_id not in topic_index:
            continue
        concepts = _concept_keys_for_obj(obj)
        index_entry = topic_index[obj_id]
        actual_path = _normalized_path(index_entry.get("topic_path", []))
        for concept, expected_path in EXPECTED_CONCEPT_TOPIC_PATHS.items():
            if concept not in concepts:
                continue
            normalized_expected = _normalized_path(expected_path)
            if actual_path == normalized_expected:
                continue
            issues.append(
                _issue(
                    code="concept_topic_path_mismatch",
                    severity="severe",
                    message=(
                        f"L1 concept '{concept}' should resolve to "
                        f"{' / '.join(expected_path)}."
                    ),
                    root_label=actual_path[0] if actual_path else "",
                    topic_label=" / ".join(actual_path),
                    topic_id=str(index_entry.get("topic_id", "") or ""),
                    obj_id=obj_id,
                )
            )
    return issues


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# Topic View Validation",
        "",
        "## Summary",
        "",
        f"- Topic count: {summary.get('topic_count', 0)}",
        f"- Topic event count: {summary.get('topic_event_count', 0)}",
        f"- Severe issues: {summary.get('severe_issue_count', 0)}",
        f"- Warning issues: {summary.get('warning_issue_count', 0)}",
        "",
        "## Manual Review Queue",
        "",
    ]
    queue = report.get("manual_topic_review_queue", [])
    if not queue:
        lines.append("- No severe topic assignment issues.")
    else:
        for item in queue:
            lines.append(
                "- {severity} {code}: {root_label} / {topic_label} {message}".format(
                    **item
                )
            )
    lines.append("")
    return "\n".join(lines)


def validate_topic_view_outputs(
    *,
    root: Path | str,
    out: Path | str | None = None,
    max_topic_event_count: int = 30,
    expected_links: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base = Path(root)
    topic_tree = load_topic_tree(base)
    topic_index = load_topic_index(base)
    share_tree = load_share_tree(base)
    obj_by_id = {
        str(obj.get("obj_id", "") or ""): obj
        for _meeting, obj in iter_l1_objects(share_tree)
        if str(obj.get("obj_id", "") or "")
    }
    expected = DEFAULT_EXPECTED_LINKS if expected_links is None else expected_links
    issues = [
        *_validate_labels(topic_tree, max_topic_event_count=max_topic_event_count),
        *_validate_expected_links(topic_index, obj_by_id, expected),
        *_validate_concept_paths(topic_index, obj_by_id),
    ]
    severe = [item for item in issues if item.get("severity") == "severe"]
    warnings = [item for item in issues if item.get("severity") != "severe"]
    topic_count = len(_topic_nodes(topic_tree))
    topic_event_count = sum(
        len([item for item in child.get("event_ids", []) if str(item).strip()])
        for _, child in _topic_nodes(topic_tree)
    )
    report = {
        "topic_tree_path": str((base / TOPIC_TREE_FILE_NAME).resolve()),
        "topic_index_path": str((base / TOPIC_INDEX_FILE_NAME).resolve()),
        "summary": {
            "topic_count": topic_count,
            "topic_event_count": topic_event_count,
            "issue_count": len(issues),
            "severe_issue_count": len(severe),
            "warning_issue_count": len(warnings),
        },
        "manual_topic_review_queue": severe,
        "warnings": warnings,
    }
    if out is not None:
        output = Path(out)
        output.mkdir(parents=True, exist_ok=True)
        _write_json(output / "topic_validation_report.json", report)
        _write_json(output / "manual_topic_review_queue.json", severe)
        (output / "topic_validation_report.md").write_text(
            _markdown_report(report),
            encoding="utf-8",
        )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate share_mem topic-tree outputs.")
    parser.add_argument("--root", default="share_mem", help="share_mem or experiment root.")
    parser.add_argument("--out", default="", help="Directory for validation report outputs.")
    parser.add_argument(
        "--max-topic-event-count",
        type=int,
        default=30,
        help="Warn when a topic has more events than this threshold.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    report = validate_topic_view_outputs(
        root=args.root,
        out=args.out or None,
        max_topic_event_count=args.max_topic_event_count,
    )
    summary = report["summary"]
    print(
        "topic validation complete: "
        f"{summary['severe_issue_count']} severe, "
        f"{summary['warning_issue_count']} warnings"
    )
    if int(summary["severe_issue_count"]) > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
