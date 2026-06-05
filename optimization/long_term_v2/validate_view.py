from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import load_json, utc_now_iso, write_json, write_text
from optimization.long_term_v2.profiles import (
    load_profile,
    profile_generic_topic_labels,
    profile_rejected_topic_labels,
    profile_type_like_labels,
)


def _issue(severity: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, **extra}


def _iter_l1_objects(tree: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for meeting in tree.get("meetings", []) or []:
        if not isinstance(meeting, dict):
            continue
        meeting_id = str(meeting.get("meeting_id", "") or "")
        for obj in meeting.get("memory_objects", []) or []:
            if not isinstance(obj, dict):
                continue
            row = dict(obj)
            row.setdefault("meeting_id", meeting_id)
            rows.append(row)
    return rows


def _has_suspect_mojibake(text: str) -> bool:
    if "\ufffd" in text:
        return True
    private_use_count = sum(1 for char in text if "\ue000" <= char <= "\uf8ff")
    if private_use_count:
        return True
    if text.count("??") >= 2 and any("\u4e00" <= char <= "\u9fff" for char in text):
        return True
    return False


def _l1_text_quality_audit(tree: dict[str, Any]) -> dict[str, Any]:
    suspect: list[dict[str, Any]] = []
    for obj in _iter_l1_objects(tree):
        text = " ".join([str(obj.get("content", "") or ""), str(obj.get("evidence", "") or "")])
        if _has_suspect_mojibake(text):
            suspect.append(
                {
                    "obj_id": obj.get("obj_id", ""),
                    "meeting_id": obj.get("meeting_id", ""),
                    "content_preview": str(obj.get("content", "") or "")[:160],
                }
            )
    return {
        "suspect_mojibake_count": len(suspect),
        "suspect_mojibake_sample": suspect[:20],
    }


def _label_issue(label: str, *, profile: dict[str, Any]) -> str:
    clean = str(label).strip().lower().replace("_", " ")
    if clean in profile_type_like_labels(profile):
        return "type_like_l2_label"
    if clean in profile_rejected_topic_labels(profile):
        return "rejected_l2_label"
    generic_labels = profile_generic_topic_labels(profile)
    if clean in generic_labels:
        return "generic_l2_label"
    parts = clean.split()
    if len(parts) == 1 and parts[0] in generic_labels:
        return "generic_l2_label"
    return ""


def validate_run(*, run_root: Path | str) -> dict[str, Any]:
    root = Path(run_root)
    issues: list[dict[str, Any]] = []
    manual_queue: list[dict[str, Any]] = []
    required = [
        root / "manifest.json",
        root / "input_snapshot" / "tree.json",
        root / "semantic_keys" / "semantic_key_index.json",
        root / "l2" / "l2_view.json",
        root / "l2" / "l2_index.json",
        root / "l3" / "l3_view.json",
        root / "l3" / "l3_index.json",
    ]
    for path in required:
        if not path.exists():
            issues.append(_issue("severe", "missing_output", f"Missing required output: {path}", path=str(path)))

    manifest = load_json(root / "manifest.json") if (root / "manifest.json").exists() else {}
    profile: dict[str, Any] = {}
    profile_path = manifest.get("profile_path")
    if profile_path and Path(str(profile_path)).exists():
        profile = load_profile(str(profile_path))
    semantic = load_json(root / "semantic_keys" / "semantic_key_index.json") if (root / "semantic_keys" / "semantic_key_index.json").exists() else {}
    l2_view = load_json(root / "l2" / "l2_view.json") if (root / "l2" / "l2_view.json").exists() else {}
    l2_index = load_json(root / "l2" / "l2_index.json") if (root / "l2" / "l2_index.json").exists() else {}
    l3_view = load_json(root / "l3" / "l3_view.json") if (root / "l3" / "l3_view.json").exists() else {}
    l3_index = load_json(root / "l3" / "l3_index.json") if (root / "l3" / "l3_index.json").exists() else {}
    tree = load_json(root / "input_snapshot" / "tree.json") if (root / "input_snapshot" / "tree.json").exists() else {}
    text_quality = _l1_text_quality_audit(tree) if tree else {"suspect_mojibake_count": 0, "suspect_mojibake_sample": []}
    if text_quality["suspect_mojibake_count"]:
        item = _issue(
            "warning",
            "l1_text_quality_mojibake",
            "Some L1 content/evidence appears to contain mojibake or private-use glyphs; treat language-quality conclusions as limited.",
            suspect_mojibake_count=text_quality["suspect_mojibake_count"],
        )
        issues.append(item)
        manual_queue.append(item)

    if semantic and len(semantic.get("objects", {}) or {}) != manifest.get("source_l1_count"):
        issues.append(_issue("warning", "semantic_key_count_mismatch", "Semantic key count differs from source L1 count."))

    for node in l2_view.get("l2_nodes", []) or []:
        code = _label_issue(str(node.get("label", "") or ""), profile=profile)
        if code:
            item = _issue("warning", code, "L2 label needs review.", l2_id=node.get("l2_id"), label=node.get("label"))
            issues.append(item)
            manual_queue.append(item)
        if not node.get("representative_l1_ids"):
            issues.append(_issue("severe", "missing_representative_l1", "L2 topic lacks representative L1 ids.", l2_id=node.get("l2_id")))
        if not node.get("creation_rationale"):
            issues.append(_issue("severe", "missing_creation_rationale", "L2 topic lacks creation rationale.", l2_id=node.get("l2_id")))
        if len(node.get("linked_obj_ids", []) or []) == 1:
            item = _issue("warning", "single_l1_topic", "L2 topic has only one linked L1.", l2_id=node.get("l2_id"))
            issues.append(item)
            manual_queue.append(item)

    for obj_id, row in (l2_index or {}).items():
        breakdown = row.get("score_breakdown", {}) or {}
        if breakdown.get("related_topics_used") and len(row.get("rationale", "")) < 40:
            issues.append(_issue("warning", "weak_related_topic_rationale", "Assignment using related_topics lacks rationale.", obj_id=obj_id))
        if not row.get("rationale"):
            issues.append(_issue("severe", "missing_assignment_rationale", "L2 assignment lacks rationale.", obj_id=obj_id))

    assigned_l3_ids = set(l3_index)
    for parent in l3_view.get("l3_parents", []) or []:
        for child in parent.get("child_l2_nodes", []) or []:
            code = _label_issue(str(child.get("label", "") or ""), profile=profile)
            if code:
                child_code = code.replace("_l2_label", "_child_l2_label")
                item = _issue(
                    "warning",
                    child_code,
                    "Child L2 label needs review.",
                    parent_l3_id=parent.get("l3_id"),
                    child_l2_id=child.get("child_l2_id"),
                    label=child.get("label"),
                )
                issues.append(item)
                manual_queue.append(item)
            count = len(child.get("linked_obj_ids", []) or [])
            if count < 3:
                item = _issue("warning", "tiny_child_l2", "Child L2 has fewer than 3 L1 objects.", child_l2_id=child.get("child_l2_id"))
                issues.append(item)
                manual_queue.append(item)
            if count > 35:
                item = _issue(
                    "warning",
                    "oversized_child_l2",
                    "Child L2 still has more than 35 L1 objects after L3 split.",
                    child_l2_id=child.get("child_l2_id"),
                    linked_l1_count=count,
                )
                issues.append(item)
                manual_queue.append(item)

    severe_count = sum(1 for issue in issues if issue["severity"] == "severe")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "severe_count": severe_count,
        "warning_count": warning_count,
        "issue_count": len(issues),
        "issues": issues,
        "manual_review_count": len(manual_queue),
        "manual_review_queue": manual_queue,
        "raw_l1_mutation_check": "validation is read-only; input snapshot is compared by caller when needed",
        "related_topics_direct_assignment": False,
        "l2_topic_count": len(l2_view.get("l2_nodes", []) or []),
        "l3_parent_count": len(l3_view.get("l3_parents", []) or []),
        "l3_assigned_l1_count": len(assigned_l3_ids),
    }
    validation_dir = root / "validation"
    write_json(
        validation_dir / "l1_input_audit.json",
        {"source_l1_count": manifest.get("source_l1_count", 0), "text_quality": text_quality},
    )
    write_json(validation_dir / "semantic_key_validation.json", {"object_count": len(semantic.get("objects", {}) or {})})
    write_json(validation_dir / "l2_validation_report.json", report)
    write_json(validation_dir / "l3_validation_report.json", report)
    write_json(validation_dir / "manual_review_queue.json", {"items": manual_queue})
    write_text(
        validation_dir / "explainability_report.md",
        "\n".join(
            [
                "# Optimization v2 Explainability Report",
                "",
                f"- severe issues: {severe_count}",
                f"- warnings: {warning_count}",
                f"- L2 topics: {report['l2_topic_count']}",
                f"- L3 parents: {report['l3_parent_count']}",
                "",
                "The v2 view uses semantic keys and assignment rationales; related_topics are optional source signals.",
                "",
            ]
        ),
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate an optimization long-term v2 run.")
    parser.add_argument("--run-root", required=True)
    args = parser.parse_args()
    report = validate_run(run_root=args.run_root)
    print(
        f"[optimization:v2] validation complete: severe={report['severe_count']} warnings={report['warning_count']}"
    )


if __name__ == "__main__":
    main()
