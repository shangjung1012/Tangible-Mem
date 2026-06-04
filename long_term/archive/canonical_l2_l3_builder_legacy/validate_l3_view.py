"""Validate materialized L3 promotion sidecars over active L2 outputs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from l3_promotion import child_l2_size_bucket
from share_mem.store import build_l1_index, load_share_tree

TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
PROMPT_CONTEXT_CHAR_THRESHOLD = 1500
COHERENT_LARGE_CHILD_HIT_RATE = 0.70


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in TOKEN_RE.findall(str(text or "").lower())
        if token.strip()
    ]


def _issue(code: str, severity: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, **details}


def _l2_nodes_by_id(l2_view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(node.get("l2_id", "") or ""): node
        for node in l2_view.get("l2_nodes", [])
        if isinstance(node, dict) and str(node.get("l2_id", "") or "").strip()
    }


def _child_event_count(child: dict[str, Any]) -> int:
    try:
        count = int(child.get("event_count", 0) or 0)
    except (TypeError, ValueError):
        count = 0
    if count:
        return count
    linked = child.get("linked_obj_ids", [])
    if isinstance(linked, list) and linked:
        return len(linked)
    timeline = child.get("timeline_digest", [])
    return len(timeline) if isinstance(timeline, list) else 0


def _source_timeline_obj_ids(l2_node: dict[str, Any]) -> list[str]:
    timeline = l2_node.get("timeline_digest", [])
    if isinstance(timeline, list) and timeline:
        return [
            str(row.get("obj_id", "") or "")
            for row in timeline
            if isinstance(row, dict) and str(row.get("obj_id", "") or "").strip()
        ]
    linked = l2_node.get("linked_obj_ids", [])
    return [str(obj_id) for obj_id in linked if str(obj_id).strip()] if isinstance(linked, list) else []


def _timeline_obj_ids(child: dict[str, Any]) -> list[str]:
    timeline = child.get("timeline_digest", [])
    if isinstance(timeline, list) and timeline:
        return [
            str(row.get("obj_id", "") or "")
            for row in timeline
            if isinstance(row, dict) and str(row.get("obj_id", "") or "").strip()
        ]
    linked = child.get("linked_obj_ids", [])
    return [str(obj_id) for obj_id in linked if str(obj_id).strip()] if isinstance(linked, list) else []


def _context_char_count(child: dict[str, Any]) -> int:
    parts = [
        str(child.get("label", "") or ""),
        str(child.get("current_state", "") or ""),
        str(child.get("split_reason", "") or ""),
    ]
    for row in child.get("timeline_digest", []) if isinstance(child.get("timeline_digest"), list) else []:
        if isinstance(row, dict):
            parts.append(str(row.get("summary", "") or row.get("content", "") or ""))
    return len("\n".join(parts))


def _coherence(child: dict[str, Any]) -> dict[str, Any]:
    criteria = [
        str(item).lower().replace("-", " ")
        for item in child.get("assignment_criteria", [])
        if str(item).strip()
    ] if isinstance(child.get("assignment_criteria"), list) else []
    rows = [row for row in child.get("timeline_digest", []) if isinstance(row, dict)] if isinstance(child.get("timeline_digest"), list) else []
    matched_rows = 0
    token_counts: Counter[str] = Counter()
    for row in rows:
        text = " ".join(
            [
                str(row.get("summary", "") or ""),
                str(row.get("content", "") or ""),
            ]
        ).lower().replace("-", " ")
        if any(hint in text for hint in criteria):
            matched_rows += 1
        token_counts.update(token for token in _tokens(text) if len(token) > 2)
    hit_rate = round(matched_rows / len(rows), 4) if rows else 0.0
    return {
        "assignment_criteria_hit_rate": hit_rate,
        "representative_keywords": [token for token, _ in token_counts.most_common(8)],
        "matched_criteria": criteria,
    }


def _scale_assessment(size_bucket: str, coherence: dict[str, Any]) -> str:
    if size_bucket != "needs_split_review":
        return size_bucket
    try:
        hit_rate = float(coherence.get("assignment_criteria_hit_rate", 0.0) or 0.0)
    except (TypeError, ValueError):
        hit_rate = 0.0
    if hit_rate >= COHERENT_LARGE_CHILD_HIT_RATE:
        return "large_coherent_needs_retrieval_slice"
    return "large_low_coherence_needs_split_review"


def _is_family_l3_parent(l3_view: dict[str, Any], parent: dict[str, Any]) -> bool:
    return (
        str(l3_view.get("source", "") or "") == "synthetic_related_topics_family_materialization"
        or str(parent.get("source", "") or "") == "related_topics_family_sidecar"
    )


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# L3 Validation Report",
        "",
        f"- Materialized L3 count: {report['materialized_l3_count']}",
        f"- Severe count: {report['severe_count']}",
        f"- Warning count: {report['warning_count']}",
        f"- Unassigned L1 count: {report['promotion_coverage']['unassigned_l1_count']}",
        f"- Duplicate assignment count: {report['promotion_coverage']['duplicate_assignment_count']}",
        "",
        "## Child Size Distribution",
    ]
    for bucket, count in sorted(report["child_size_distribution"].items()):
        lines.append(f"- {bucket}: {count}")
    lines.extend(["", "## Issues"])
    if not report["issues"]:
        lines.append("No issues.")
    else:
        for issue in report["issues"]:
            lines.append(f"- [{issue['severity']}] {issue['code']}: {issue['message']}")
    lines.append("")
    return "\n".join(lines)


def validate_l3_view_outputs(
    *,
    share_mem_root: Path | str = REPO_ROOT / "share_mem",
    l2_root: Path | str = REPO_ROOT / "long_term" / "l2",
    l3_root: Path | str = REPO_ROOT / "long_term" / "l3",
    out: Path | str | None = None,
    prompt_context_char_threshold: int = PROMPT_CONTEXT_CHAR_THRESHOLD,
) -> dict[str, Any]:
    share_root = Path(share_mem_root)
    l2_path = Path(l2_root)
    l3_path = Path(l3_root)
    out_root = Path(out) if out is not None else l3_path / "validation"
    share_tree = load_share_tree(share_root)
    l1_index = build_l1_index(share_tree)
    l2_view = _load_json(l2_path / "l2_view.json")
    l3_view = _load_json(l3_path / "l3_view.json")
    l3_index = _load_json(l3_path / "l3_index.json")
    merge_review = _load_json(l3_path / "l2_merge_review.json")
    l2_lookup = _l2_nodes_by_id(l2_view if isinstance(l2_view, dict) else {})
    l3_index = l3_index if isinstance(l3_index, dict) else {}

    issues: list[dict[str, Any]] = []
    manual_queue: list[dict[str, Any]] = []
    size_distribution: Counter[str] = Counter()
    scale_assessment_distribution: Counter[str] = Counter()
    child_reports: list[dict[str, Any]] = []
    total_unassigned = 0
    total_duplicate = 0
    invalid_index_count = 0
    merge_review_ids = {
        str(row.get("source_child_l2_id", "") or "")
        for row in merge_review.get("merge_reviews", [])
        if isinstance(row, dict)
    } if isinstance(merge_review, dict) else set()

    for parent in l3_view.get("l3_nodes", []) if isinstance(l3_view, dict) else []:
        if not isinstance(parent, dict):
            continue
        l3_id = str(parent.get("l3_id", "") or "")
        family_parent = _is_family_l3_parent(l3_view, parent if isinstance(parent, dict) else {})
        source_l2_id = str(parent.get("promoted_from_l2_id", "") or "")
        source_node = l2_lookup.get(source_l2_id)
        if not family_parent and not source_node:
            issues.append(_issue("promoted_source_l2_missing", "severe", "L3 parent references a missing source L2.", l3_id=l3_id, source_l2_id=source_l2_id))
            continue
        source_ids = _source_timeline_obj_ids(source_node) if source_node else []
        source_set = set(source_ids)
        assigned_sequence: list[str] = []
        child_nodes = [child for child in parent.get("child_l2_nodes", []) if isinstance(child, dict)] if isinstance(parent.get("child_l2_nodes"), list) else []
        if not family_parent and len(child_nodes) < 2:
            issues.append(_issue("needs_split_review", "warning", "Promoted L2 has fewer than two child L2 nodes.", l3_id=l3_id, source_l2_id=source_l2_id))
        for child in child_nodes:
            child_id = str(child.get("l2_id", "") or "")
            child_ids = _timeline_obj_ids(child)
            assigned_sequence.extend(child_ids)
            if family_parent:
                child_source_node = l2_lookup.get(child_id)
                if not child_source_node:
                    issues.append(_issue("child_l2_source_missing", "severe", "Family L3 child references a missing L2 source.", l3_id=l3_id, child_l2_id=child_id))
                    child_source_set: set[str] = set()
                else:
                    child_source_set = set(_source_timeline_obj_ids(child_source_node))
                for obj_id in sorted(set(child_ids) - child_source_set):
                    issues.append(_issue("child_assignment_outside_child_l2", "severe", "Family L3 child references an L1 outside its child L2.", l3_id=l3_id, child_l2_id=child_id, obj_id=obj_id))
            event_count = _child_event_count(child)
            bucket = child_l2_size_bucket(event_count)
            size_distribution[bucket] += 1
            char_count = _context_char_count(child)
            coherence = _coherence(child)
            scale_assessment = _scale_assessment(bucket, coherence)
            scale_assessment_distribution[scale_assessment] += 1
            child_report = {
                "parent_l3_id": l3_id,
                "source_l2_id": source_l2_id,
                "child_l2_id": child_id,
                "label": str(child.get("label", "") or ""),
                "event_count": event_count,
                "size_bucket": bucket,
                "scale_assessment": scale_assessment,
                "formatted_context_char_count": char_count,
                "coherence": coherence,
            }
            child_reports.append(child_report)
            if bucket == "needs_merge_review":
                issue = _issue("tiny_child_l2", "warning", "Child L2 has fewer than three L1 events and should be reviewed for merge.", **child_report)
                issues.append(issue)
                manual_queue.append(issue)
                if child_id not in merge_review_ids:
                    issues.append(_issue("tiny_child_l2_missing_merge_review", "warning", "Tiny child L2 is absent from l2_merge_review.json.", parent_l3_id=l3_id, child_l2_id=child_id))
            elif scale_assessment == "large_low_coherence_needs_split_review":
                issue = _issue("oversized_child_l2", "warning", "Child L2 is still too large and should be reviewed for another split.", **child_report)
                issues.append(issue)
                manual_queue.append(issue)
            if char_count > prompt_context_char_threshold:
                issues.append(_issue("needs_retrieval_slice", "warning", "Child L2 full timeline exceeds prompt context threshold.", **child_report))
        assigned_counts = Counter(assigned_sequence)
        duplicates = {obj_id for obj_id, count in assigned_counts.items() if count > 1}
        total_duplicate += len(duplicates)
        for obj_id in sorted(duplicates):
            issues.append(_issue("duplicate_child_assignment", "severe", "Source L1 is assigned to multiple child L2 nodes.", l3_id=l3_id, obj_id=obj_id))
        if not family_parent:
            unassigned = source_set - set(assigned_sequence)
            outside_source = set(assigned_sequence) - source_set
            total_unassigned += len(unassigned)
            for obj_id in sorted(unassigned):
                issues.append(_issue("unassigned_source_l1", "severe", "Promoted source L2 has an L1 item missing from child L2 assignments.", l3_id=l3_id, obj_id=obj_id))
            for obj_id in sorted(outside_source):
                issues.append(_issue("child_assignment_outside_source_l2", "severe", "Child L2 references an L1 outside the promoted source L2.", l3_id=l3_id, obj_id=obj_id))

    for obj_id, row in l3_index.items():
        if obj_id not in l1_index:
            invalid_index_count += 1
            issues.append(_issue("l3_index_obj_missing_from_share_mem", "severe", "l3_index references an obj_id absent from share_mem.", obj_id=obj_id))
            continue
        source_l2_id = str(row.get("source_l2_id", "") or row.get("child_l2_id", "") or "")
        source_node = l2_lookup.get(source_l2_id)
        if source_node and obj_id not in set(_source_timeline_obj_ids(source_node)):
            invalid_index_count += 1
            issues.append(_issue("l3_index_obj_not_in_source_l2", "severe", "l3_index obj_id is not in its promoted source L2 timeline.", obj_id=obj_id, source_l2_id=source_l2_id))

    severe_count = sum(1 for issue in issues if issue["severity"] == "severe")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    report = {
        "schema_version": 1,
        "share_mem_root": str(share_root.resolve()),
        "l2_root": str(l2_path.resolve()),
        "l3_root": str(l3_path.resolve()),
        "materialized_l3_count": len(l3_view.get("l3_nodes", [])) if isinstance(l3_view, dict) else 0,
        "promotion_coverage": {
            "unassigned_l1_count": total_unassigned,
            "duplicate_assignment_count": total_duplicate,
            "invalid_l3_index_count": invalid_index_count,
        },
        "child_size_distribution": dict(size_distribution),
        "scale_assessment_distribution": dict(scale_assessment_distribution),
        "child_l2_reports": child_reports,
        "issue_count": len(issues),
        "severe_count": severe_count,
        "warning_count": warning_count,
        "issues": issues,
        "manual_review_count": len(manual_queue),
    }
    _write_json(out_root / "l3_validation_report.json", report)
    _write_json(out_root / "manual_l3_review_queue.json", manual_queue)
    (out_root / "l3_validation_report.md").write_text(_markdown_report(report), encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate generated L3 promotion sidecars.")
    parser.add_argument("--share-mem-root", default=str(REPO_ROOT / "share_mem"))
    parser.add_argument("--l2-root", default=str(REPO_ROOT / "long_term" / "l2"))
    parser.add_argument("--l3-root", default=str(REPO_ROOT / "long_term" / "l3"))
    parser.add_argument("--out", default=str(REPO_ROOT / "long_term" / "l3" / "validation"))
    parser.add_argument("--prompt-context-char-threshold", type=int, default=PROMPT_CONTEXT_CHAR_THRESHOLD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    report = validate_l3_view_outputs(
        share_mem_root=args.share_mem_root,
        l2_root=args.l2_root,
        l3_root=args.l3_root,
        out=args.out,
        prompt_context_char_threshold=args.prompt_context_char_threshold,
    )
    print(
        "[long_term] L3 validation complete: "
        f"{report['severe_count']} severe, {report['warning_count']} warnings"
    )
    print(f"Report: {Path(args.out) / 'l3_validation_report.json'}")
    if report["severe_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
