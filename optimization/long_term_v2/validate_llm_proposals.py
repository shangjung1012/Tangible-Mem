from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json
from optimization.long_term_v2.profiles import profile_generic_topic_labels, profile_type_like_labels
from optimization.long_term_v2.text_utils import normalize_phrase
from share_mem.store import iter_l1_objects


FUNCTION_WORD_LABELS = {"you", "we", "so", "of", "it", "which", "uh", "um", "mm", "hmm", "in", "is", "be"}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _label_rejection(label: str, *, profile: dict[str, Any]) -> str:
    clean = normalize_phrase(label)
    if not clean:
        return "empty_label"
    generic = profile_generic_topic_labels(profile)
    type_like = profile_type_like_labels(profile)
    if clean in type_like or clean in generic or clean in FUNCTION_WORD_LABELS:
        return "generic_or_type_like_label"
    if len(clean.split()) == 1 and clean in generic:
        return "generic_or_type_like_label"
    return ""


def _known_ids(run_root: Path) -> tuple[set[str], dict[str, dict[str, Any]]]:
    tree_path = run_root / "input_snapshot" / "tree.json"
    obj_ids = set()
    if tree_path.exists():
        for _meeting, obj in iter_l1_objects(load_json(tree_path)):
            obj_ids.add(str(obj.get("obj_id", "") or ""))
    l2_view = load_json(run_root / "l2" / "l2_view.json")
    l2_by_id = {str(node.get("l2_id", "")): node for node in l2_view.get("l2_nodes", []) or []}
    if not obj_ids:
        obj_ids = {
            str(obj_id)
            for node in l2_by_id.values()
            for obj_id in (node.get("linked_obj_ids", []) or [])
        }
    return obj_ids, l2_by_id


def _proposal_record(
    *,
    proposal_id: str,
    proposal_type: str,
    raw: dict[str, Any],
    validation_status: str,
    rejection_reason: str = "",
) -> dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "proposal_type": proposal_type,
        "target_ids": [
            str(raw.get(key))
            for key in ("source_l2_id", "target_l2_id", "l2_id", "obj_id")
            if raw.get(key)
        ],
        "representative_l1_ids": [str(value) for value in raw.get("representative_l1_ids", []) or []],
        "rationale": str(raw.get("rationale", "") or ""),
        "confidence": _safe_float(raw.get("confidence")),
        "validation_status": validation_status,
        "rejection_reason": rejection_reason,
        "raw_proposal": raw,
    }


def validate_llm_proposals(*, run_root: Path | str, profile: dict[str, Any]) -> dict[str, Any]:
    root = ensure_optimization_output(run_root)
    proposal_path = root / "l2" / "llm_induction_proposals.json"
    proposals = load_json(proposal_path) if proposal_path.exists() else {}
    obj_ids, l2_by_id = _known_ids(root)
    records: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []
    sequence = 1

    def add_record(proposal_type: str, raw: dict[str, Any], status: str, reason: str = "") -> None:
        nonlocal sequence
        record = _proposal_record(
            proposal_id=f"LLM-PROP-{sequence:04d}",
            proposal_type=proposal_type,
            raw=raw,
            validation_status=status,
            rejection_reason=reason,
        )
        records.append(record)
        if status != "accepted":
            queue.append(record)
        sequence += 1

    for row in proposals.get("merge_candidates", []) or []:
        source = str(row.get("source_l2_id", "") or "")
        target = str(row.get("target_l2_id", "") or "")
        reps = {str(value) for value in row.get("representative_l1_ids", []) or []}
        if source not in l2_by_id or target not in l2_by_id or not reps <= obj_ids:
            add_record("merge_candidate", row, "rejected", "unknown_references")
        elif _safe_float(row.get("confidence")) < 0.5:
            add_record("merge_candidate", row, "review", "low_confidence_manual_review")
        else:
            add_record("merge_candidate", row, "accepted")

    for row in proposals.get("split_candidates", []) or []:
        source = str(row.get("source_l2_id", "") or "")
        reps = {str(value) for value in row.get("representative_l1_ids", []) or []}
        labels = [str(label) for label in row.get("proposed_child_labels", []) or []]
        label_reasons = [_label_rejection(label, profile=profile) for label in labels]
        if source not in l2_by_id or not reps <= obj_ids:
            add_record("split_candidate", row, "rejected", "unknown_references")
        elif any(label_reasons):
            add_record("split_candidate", row, "rejected", "generic_or_type_like_label")
        elif _safe_float(row.get("confidence")) < 0.5:
            add_record("split_candidate", row, "review", "low_confidence_manual_review")
        elif len(labels) < 2:
            add_record("split_candidate", row, "rejected", "insufficient_child_labels")
        else:
            add_record("split_candidate", row, "accepted")

    for row in proposals.get("assignment_concerns", []) or []:
        obj_id = str(row.get("obj_id", "") or "")
        l2_id = str(row.get("l2_id", "") or "")
        if obj_id not in obj_ids or l2_id not in l2_by_id:
            add_record("assignment_concern", row, "rejected", "unknown_references")
        elif _safe_float(row.get("confidence")) < 0.5:
            add_record("assignment_concern", row, "review", "low_confidence_manual_review")
        else:
            add_record("assignment_concern", row, "accepted")

    accepted_count = sum(1 for row in records if row["validation_status"] == "accepted")
    rejected_count = sum(1 for row in records if row["validation_status"] == "rejected")
    review_count = sum(1 for row in records if row["validation_status"] == "review")
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "status": "pass" if records and rejected_count >= 0 else "warning",
        "proposal_count": len(records),
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "review_count": review_count,
        "proposals": records,
    }
    write_json(root / "l2" / "llm_proposal_validation.json", report)
    write_json(root / "l2" / "llm_proposal_review_queue.json", {"items": queue})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate sidecar-only LLM induction proposals.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    from optimization.long_term_v2.profiles import load_profile

    report = validate_llm_proposals(run_root=args.run_root, profile=load_profile(args.profile))
    print(
        "[optimization:v2] LLM proposal validation complete: "
        f"accepted={report['accepted_count']} rejected={report['rejected_count']} review={report['review_count']}"
    )


if __name__ == "__main__":
    main()
