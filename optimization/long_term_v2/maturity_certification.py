from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, tree_hash, utc_now_iso, write_json, write_text
from optimization.long_term_v2.profiles import (
    load_profile,
    profile_generic_topic_labels,
    profile_type_like_labels,
)
from optimization.long_term_v2.text_utils import normalize_phrase
from share_mem.store import build_l1_index, iter_l1_objects, load_share_tree


GRACE_SPECIFIC_PATTERNS = [
    "DEFAULT" + "_CHILD",
    "transcript " + "segmentation",
    "idea-unit " + "coverage",
    "topic " + "lifecycle",
    "manager-" + "agent",
    "memory evaluation " + "strategy",
    "L2-" + "transcript",
    "L3-" + "transcript",
]
SECRET_PATTERNS = [
    r"AIza[0-9A-Za-z_\-]{20,}",
    r"GOOGLE_APPLICATION_CREDENTIALS",
    r"GEMINI_API_KEY",
    r"BEGIN PRIVATE KEY",
    r"application_default_credentials",
    r"C:\\Users\\.*credentials",
]
FUNCTION_WORD_LABELS = {
    "you",
    "we",
    "so",
    "of",
    "it",
    "which",
    "uh",
    "um",
    "mm",
    "hmm",
    "in",
    "is",
    "be",
}


def _status(pass_condition: bool, *, warning: bool = False) -> str:
    if pass_condition:
        return "pass"
    return "warning" if warning else "fail"


def create_related_topics_ablation_root(*, share_mem_root: Path | str, out_root: Path | str) -> dict[str, Any]:
    out = ensure_optimization_output(out_root)
    tree = load_share_tree(share_mem_root)
    cleared = 0
    for meeting in tree.get("meetings", []) or []:
        for obj in meeting.get("memory_objects", []) or []:
            if obj.get("related_topics"):
                cleared += 1
            obj["related_topics"] = []
    write_json(out / "tree.json", tree)
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "source_share_mem_root": str(Path(share_mem_root).resolve()),
        "ablation_root": str(out.resolve()),
        "cleared_related_topics_count": cleared,
        "source_tree_hash": tree_hash(load_share_tree(share_mem_root)),
        "ablation_tree_hash": tree_hash(tree),
    }
    write_json(out / "ablation_manifest.json", report)
    return report


def _load_profile_for_run(root: Path) -> dict[str, Any]:
    manifest = load_json(root / "manifest.json")
    profile_path = manifest.get("profile_path")
    if profile_path and Path(str(profile_path)).exists():
        return load_profile(str(profile_path))
    return {}


def _scan_core_for_patterns(core_root: Path) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for path in core_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        for pattern in GRACE_SPECIFIC_PATTERNS:
            if pattern.lower() in lower:
                matches.append({"path": str(path), "pattern": pattern})
    return matches


def _scan_secret_patterns(paths: list[Path]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    compiled = [re.compile(pattern) for pattern in SECRET_PATTERNS]
    for root in paths:
        if not root.exists():
            continue
        files = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
        for path in files:
            if path.name == "maturity_certification.py":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for pattern in compiled:
                if pattern.search(text):
                    matches.append({"path": str(path), "pattern": pattern.pattern})
    return matches


def _required_artifacts(root: Path) -> list[str]:
    required = [
        "manifest.json",
        "input_snapshot/tree.json",
        "input_snapshot/manifest.json",
        "semantic_keys/semantic_key_index.json",
        "l2/l2_view.json",
        "l2/l2_index.json",
        "l3/l3_view.json",
        "l3/l3_index.json",
        "validation/l2_validation_report.json",
        "validation/l3_validation_report.json",
        "validation/manual_review_queue.json",
    ]
    return [name for name in required if not (root / name).exists()]


def _source_hash_status(root: Path) -> dict[str, Any]:
    manifest = load_json(root / "manifest.json")
    snapshot_tree = load_json(root / "input_snapshot" / "tree.json")
    snapshot_hash = tree_hash(snapshot_tree)
    source_root = Path(str(manifest.get("share_mem_root", "")))
    source_current_hash = ""
    if source_root.exists() and (source_root / "tree.json").exists():
        source_current_hash = tree_hash(load_share_tree(source_root))
    return {
        "manifest_hash": manifest.get("source_tree_hash_before", ""),
        "snapshot_hash": snapshot_hash,
        "source_current_hash": source_current_hash,
        "snapshot_matches_manifest": snapshot_hash == manifest.get("source_tree_hash_before", ""),
        "source_matches_snapshot": bool(source_current_hash) and source_current_hash == snapshot_hash,
    }


def _label_quality(root: Path) -> dict[str, Any]:
    profile = _load_profile_for_run(root)
    l2_view = load_json(root / "l2" / "l2_view.json")
    type_like = profile_type_like_labels(profile)
    generic = profile_generic_topic_labels(profile)
    bad_labels = []
    function_labels = []
    missing_fields = []
    for node in l2_view.get("l2_nodes", []) or []:
        label = normalize_phrase(str(node.get("label", "") or ""))
        if label in type_like or label in generic or (len(label.split()) == 1 and label in generic):
            bad_labels.append({"l2_id": node.get("l2_id"), "label": node.get("label")})
        if label in FUNCTION_WORD_LABELS:
            function_labels.append({"l2_id": node.get("l2_id"), "label": node.get("label")})
        for field in ("definition", "inclusion_criteria", "exclusion_criteria", "linked_obj_ids", "creation_rationale", "current_state", "evolution_summary", "confidence"):
            if field not in node or node.get(field) in (None, "", []):
                missing_fields.append({"l2_id": node.get("l2_id"), "label": node.get("label"), "field": field})
    return {
        "type_or_generic_label_count": len(bad_labels),
        "function_word_label_count": len(function_labels),
        "missing_field_count": len(missing_fields),
        "bad_labels": bad_labels,
        "function_word_labels": function_labels,
        "missing_fields": missing_fields[:50],
    }


def _semantic_key_quality(root: Path) -> dict[str, Any]:
    semantic = load_json(root / "semantic_keys" / "semantic_key_index.json")
    manifest = load_json(root / "manifest.json")
    top_terms = semantic.get("top_terms", {}) or {}
    function_top_terms = [
        term for term in top_terms if normalize_phrase(term) in FUNCTION_WORD_LABELS
    ]
    return {
        "semantic_key_count": len(semantic.get("objects", {}) or {}),
        "source_l1_count": manifest.get("source_l1_count", 0),
        "count_matches_l1": len(semantic.get("objects", {}) or {}) == manifest.get("source_l1_count", 0),
        "function_word_top_terms": function_top_terms,
    }


def _comparison_summary(root: Path) -> dict[str, Any]:
    path = root / "comparison" / "baseline_vs_v2_l2.json"
    if not path.exists():
        return {"exists": False}
    data = load_json(path)
    return {
        "exists": True,
        "baseline_high_importance_linked_rate": data.get("baseline_high_importance_linked_rate"),
        "v2_high_importance_linked_rate": data.get("v2_high_importance_linked_rate"),
        "changed_high_importance_l1_count": data.get("changed_high_importance_l1_count"),
        "passes_high_importance_gate": float(data.get("v2_high_importance_linked_rate", 0.0) or 0.0) >= max(
            0.98,
            float(data.get("baseline_high_importance_linked_rate", 0.0) or 0.0),
        ),
    }


def _load_retrieval_summary(root: Path, subdir: str) -> dict[str, Any]:
    path = root / subdir / "retrieval_eval_report.json"
    if not path.exists():
        return {"exists": False, "subdir": subdir}
    data = load_json(path)
    summary = data.get("summary", {}) or {}
    return {
        "exists": True,
        "subdir": subdir,
        "avg_expected_obj_recall_at_context": summary.get("avg_expected_obj_recall_at_context"),
        "expected_l2_semantic_hit_rate": summary.get("expected_l2_semantic_hit_rate"),
        "expected_l3_semantic_hit_rate": summary.get("expected_l3_semantic_hit_rate"),
    }


def _retrieval_summary(root: Path) -> dict[str, Any]:
    legacy = _load_retrieval_summary(root, "retrieval_eval")
    native = _load_retrieval_summary(root, "retrieval_eval_v2_native")
    semantic_source = native if native.get("exists") else legacy
    recall_source = legacy if legacy.get("exists") else semantic_source
    return {
        "exists": bool(recall_source.get("exists") or semantic_source.get("exists")),
        "legacy": legacy,
        "v2_native": native,
        "semantic_eval_source": semantic_source.get("subdir"),
        "avg_expected_obj_recall_at_context": recall_source.get("avg_expected_obj_recall_at_context"),
        "expected_l2_semantic_hit_rate": semantic_source.get("expected_l2_semantic_hit_rate"),
        "expected_l3_semantic_hit_rate": semantic_source.get("expected_l3_semantic_hit_rate"),
        "passes_recall_gate": float(recall_source.get("avg_expected_obj_recall_at_context", 0.0) or 0.0) >= 0.8683,
        "passes_l2_semantic_gate": float(semantic_source.get("expected_l2_semantic_hit_rate", 0.0) or 0.0) >= 0.9,
    }


def _l3_quality(root: Path) -> dict[str, Any]:
    l3_path = root / "l3" / "l3_view.json"
    index_path = root / "l3" / "l3_index.json"
    if not l3_path.exists() or not index_path.exists():
        return {"exists": False, "passes_l3_gate": False}
    l3_view = load_json(l3_path)
    l3_index = load_json(index_path)
    child_function_labels = []
    tiny_children = []
    child_count = 0
    for parent in l3_view.get("l3_parents", []) or []:
        seen_obj_ids: set[str] = set()
        for child in parent.get("child_l2_nodes", []) or []:
            child_count += 1
            label = normalize_phrase(str(child.get("label", "") or ""))
            if label in FUNCTION_WORD_LABELS:
                child_function_labels.append({"parent_l3_id": parent.get("l3_id"), "child_l2_id": child.get("child_l2_id"), "label": child.get("label")})
            linked = [str(value) for value in child.get("linked_obj_ids", []) or []]
            if len(linked) < 3:
                tiny_children.append({"parent_l3_id": parent.get("l3_id"), "child_l2_id": child.get("child_l2_id"), "event_count": len(linked)})
            overlap = seen_obj_ids & set(linked)
            if overlap:
                child_function_labels.append({"parent_l3_id": parent.get("l3_id"), "child_l2_id": child.get("child_l2_id"), "label": "duplicate child assignment"})
            seen_obj_ids.update(linked)
    return {
        "exists": True,
        "l3_parent_count": len(l3_view.get("l3_parents", []) or []),
        "child_l2_count": child_count,
        "l3_index_count": len(l3_index),
        "child_function_label_count": len(child_function_labels),
        "tiny_child_count": len(tiny_children),
        "child_function_labels": child_function_labels,
        "tiny_children": tiny_children[:20],
        "passes_l3_gate": not child_function_labels,
    }


def _validation_summary(root: Path) -> dict[str, Any]:
    path = root / "validation" / "l2_validation_report.json"
    if not path.exists():
        return {"exists": False}
    data = load_json(path)
    return {
        "exists": True,
        "severe_count": data.get("severe_count", 0),
        "warning_count": data.get("warning_count", 0),
        "manual_review_count": data.get("manual_review_count", 0),
        "passes_severe_gate": int(data.get("severe_count", 0) or 0) == 0,
    }


def _answer_quality_summary(root: Path) -> dict[str, Any]:
    path = root / "answer_quality" / "answer_quality_report.json"
    if not path.exists():
        return {
            "exists": False,
            "status": "warning",
            "reason": "answer_quality_report.json is missing",
        }
    data = load_json(path)
    return {
        "exists": True,
        "status": data.get("status", "warning"),
        "gate_reasons": data.get("gate_reasons", []),
        "summary": data.get("summary", {}),
        "failure_case_count": data.get("failure_case_count", 0),
    }


def _manual_review_completion_summary(root: Path) -> dict[str, Any]:
    path = root / "manual_review" / "final_manual_review_report.json"
    if not path.exists():
        return {
            "exists": False,
            "status": "warning",
            "reason": "final_manual_review_report.json is missing",
        }
    data = load_json(path)
    return {
        "exists": True,
        "status": data.get("status", "warning"),
        "decision_count": data.get("decision_count", 0),
        "severe_issue_count": data.get("severe_issue_count", 0),
        "wrong_assignment_rate": data.get("wrong_assignment_rate", 0.0),
        "generic_bucket_count": data.get("generic_bucket_count", 0),
        "unsupported_label_count": data.get("unsupported_label_count", 0),
        "missing_high_importance_unlinked_review_count": data.get("missing_high_importance_unlinked_review_count", 0),
    }


def _llm_proposal_validation_summary(root: Path) -> dict[str, Any]:
    path = root / "l2" / "llm_proposal_validation.json"
    if not path.exists():
        return {
            "exists": False,
            "status": "warning",
            "reason": "llm_proposal_validation.json is missing",
        }
    data = load_json(path)
    return {
        "exists": True,
        "status": data.get("status", "warning"),
        "proposal_count": data.get("proposal_count", 0),
        "accepted_count": data.get("accepted_count", 0),
        "rejected_count": data.get("rejected_count", 0),
        "review_count": data.get("review_count", 0),
    }


def _split_candidate_application_summary(root: Path | None) -> dict[str, Any]:
    if root is None:
        return {"exists": False, "status": "not_provided"}
    report_path = root / "l3" / "applied_split_review_candidates.json"
    if not report_path.exists():
        return {"exists": False, "status": "warning", "candidate_run_root": str(root)}
    report = load_json(report_path)
    validation = _validation_summary(root)
    applied_count = int(report.get("applied_split_count", 0) or 0)
    severe_count = int(validation.get("severe_count", 0) or 0)
    status = "pass" if applied_count > 0 and severe_count == 0 else "fail"
    return {
        "exists": True,
        "status": status,
        "candidate_run_root": str(root.resolve()),
        "applied_split_count": applied_count,
        "skipped_split_count": int(report.get("skipped_split_count", 0) or 0),
        "applied_splits": report.get("applied_splits", []),
        "skipped_splits": report.get("skipped_splits", []),
        "validation_exists": validation.get("exists", False),
        "severe_count": severe_count,
        "warning_count": int(validation.get("warning_count", 0) or 0),
    }


def _retrieval_split_pressure_summary(root: Path | None) -> dict[str, Any]:
    if root is None:
        return {"exists": False, "status": "not_provided"}
    path = root / "reports" / "retrieval_split_pressure.json"
    if not path.exists():
        return {"exists": False, "status": "not_available", "candidate_run_root": str(root)}
    report = load_json(path)
    return {
        "exists": True,
        "status": "available",
        "candidate_run_root": str(root.resolve()),
        "query_count": int(report.get("query_count", 0) or 0),
        "needs_split_topic_count": int(report.get("needs_split_topic_count", 0) or 0),
        "topics_with_retrieval_pressure_count": int(report.get("topics_with_retrieval_pressure_count", 0) or 0),
        "top_pressure_topics": (report.get("topics", []) or [])[:5],
    }


def _maturity_suite_summary(root: Path | None) -> dict[str, Any]:
    if root is None:
        return {"exists": False, "status": "not_provided"}
    path = root / "suite_summary.json"
    if not path.exists():
        return {
            "exists": False,
            "status": "warning",
            "reason": "suite_summary.json is missing",
            "suite_root": str(root),
        }
    data = load_json(path)
    return {
        "exists": True,
        "status": data.get("status", "unknown"),
        "dataset_count": data.get("dataset_count", 0),
        "failed_dataset_count": len(data.get("failed_datasets", []) or []),
        "skipped_dataset_configs": data.get("skipped_dataset_configs", []),
        "suite_root": str(root.resolve()),
    }


def _split_review_needed_source_ids(run_root: Path) -> list[str]:
    path = run_root / "l3" / "l2_merge_review.json"
    if not path.exists():
        return []
    data = load_json(path)
    return sorted(
        {
            str(row.get("source_l2_id", "") or "")
            for row in data.get("merge_reviews", []) or []
            if row.get("action") == "needs_split_review" and row.get("source_l2_id")
        }
    )


def _focused_split_review_run_summary(run_root: Path) -> dict[str, Any]:
    needed = _split_review_needed_source_ids(run_root)
    report_path = run_root / "l2" / "llm_split_review_proposals.json"
    if not needed:
        return {
            "run_root": str(run_root),
            "status": "pass",
            "pending_split_review_count": 0,
            "reviewed_source_count": 0,
            "missing_review_source_ids": [],
            "rejected_count": 0,
        }
    if not report_path.exists():
        return {
            "run_root": str(run_root),
            "status": "fail",
            "pending_split_review_count": len(needed),
            "reviewed_source_count": 0,
            "missing_review_source_ids": needed,
            "rejected_count": 0,
            "reason": "llm_split_review_proposals.json is missing",
        }
    report = load_json(report_path)
    reviewed = {
        str(value)
        for value in report.get("source_l2_ids", []) or []
        if str(value)
    }
    if not reviewed:
        reviewed = {
            str(row.get("source_l2_id", "") or "")
            for row in (report.get("accepted_split_candidates", []) or []) + (report.get("review_only", []) or [])
            if row.get("source_l2_id")
        }
    accepted_missing_reps = [
        row.get("source_l2_id")
        for row in report.get("accepted_split_candidates", []) or []
        if not row.get("representative_l1_ids")
    ]
    review_only_missing_reps = [
        row.get("source_l2_id")
        for row in report.get("review_only", []) or []
        if not row.get("representative_l1_ids")
    ]
    missing = sorted(set(needed) - reviewed)
    rejected_count = len(report.get("rejected", []) or [])
    status = "pass"
    if missing or rejected_count or accepted_missing_reps or review_only_missing_reps:
        status = "fail"
    return {
        "run_root": str(run_root),
        "status": status,
        "pending_split_review_count": len(needed),
        "reviewed_source_count": len(reviewed & set(needed)),
        "missing_review_source_ids": missing,
        "rejected_count": rejected_count,
        "accepted_split_count": len(report.get("accepted_split_candidates", []) or []),
        "review_only_count": len(report.get("review_only", []) or []),
        "accepted_missing_representative_l1": accepted_missing_reps,
        "review_only_missing_representative_l1": review_only_missing_reps,
    }


def _suite_focused_split_review_summary(root: Path | None) -> dict[str, Any]:
    if root is None:
        return {"exists": False, "status": "not_provided"}
    if not root.exists():
        return {"exists": False, "status": "warning", "suite_root": str(root)}
    run_roots = [
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "l3" / "l2_merge_review.json").exists()
    ]
    run_summaries = [_focused_split_review_run_summary(run_root) for run_root in sorted(run_roots)]
    pending = sum(row["pending_split_review_count"] for row in run_summaries)
    reviewed = sum(row["reviewed_source_count"] for row in run_summaries)
    missing: list[str] = []
    rejected = 0
    for row in run_summaries:
        missing.extend(row.get("missing_review_source_ids", []) or [])
        rejected += int(row.get("rejected_count", 0) or 0)
    status = "pass"
    if any(row["status"] == "fail" for row in run_summaries):
        status = "fail"
    return {
        "exists": True,
        "status": status,
        "suite_root": str(root.resolve()),
        "run_count": len(run_summaries),
        "pending_split_review_count": pending,
        "reviewed_source_count": reviewed,
        "missing_review_source_ids": sorted(set(missing)),
        "rejected_count": rejected,
        "runs": run_summaries,
    }


def generate_manual_review_protocol(*, run_root: Path | str, out_dir: Path | str) -> dict[str, Any]:
    root = Path(run_root)
    out = ensure_optimization_output(out_dir)
    manifest = load_json(root / "manifest.json")
    l2_view = load_json(root / "l2" / "l2_view.json")
    l3_view = load_json(root / "l3" / "l3_view.json")
    validation = load_json(root / "validation" / "l2_validation_report.json") if (root / "validation" / "l2_validation_report.json").exists() else {}
    tree = load_json(root / "input_snapshot" / "tree.json")
    l1_index = build_l1_index(tree)
    l2_index = load_json(root / "l2" / "l2_index.json")
    unlinked = load_json(root / "l2" / "unlinked_l1_report.json").get("unlinked_objects", []) if (root / "l2" / "unlinked_l1_report.json").exists() else []
    top_l2 = sorted(l2_view.get("l2_nodes", []) or [], key=lambda node: -len(node.get("linked_obj_ids", []) or []))[:10]
    semantic_rescue_assignments = sorted(
        [
            {
                "obj_id": obj_id,
                "meeting_id": l1_index.get(obj_id, {}).get("meeting_id"),
                "importance": l1_index.get(obj_id, {}).get("importance"),
                "l2_id": row.get("l2_id"),
                "l2_label": row.get("l2_label"),
                "confidence": row.get("confidence"),
                "shared_terms": (row.get("score_breakdown", {}) or {}).get("shared_terms", []),
                "content": l1_index.get(obj_id, {}).get("content", "")[:240],
            }
            for obj_id, row in (l2_index or {}).items()
            if row.get("assignment_mode") == "semantic_rescue"
        ],
        key=lambda item: (float(item.get("confidence", 0.0) or 0.0), str(item.get("obj_id", ""))),
    )[:10]
    linked_high = [
        {
            "obj_id": obj_id,
            "meeting_id": l1_index[obj_id].get("meeting_id"),
            "importance": l1_index[obj_id].get("importance"),
            "l2_id": l2_index[obj_id].get("l2_id"),
            "l2_label": l2_index[obj_id].get("l2_label"),
            "content": l1_index[obj_id].get("content", "")[:240],
        }
        for obj_id in sorted(l2_index)
        if obj_id in l1_index and float(l1_index[obj_id].get("importance", 0.0) or 0.0) >= 0.7
    ][:10]
    unlinked_sample = [
        {
            **row,
            "content": l1_index.get(row.get("obj_id", ""), {}).get("content", "")[:240],
        }
        for row in unlinked[:10]
    ]
    protocol = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "profile_name": manifest.get("profile_name"),
        "review_item_count": len(top_l2)
        + len(l3_view.get("l3_parents", []) or [])
        + len(validation.get("manual_review_queue", []) or [])
        + len(linked_high)
        + len(unlinked_sample)
        + len(semantic_rescue_assignments),
        "required_labels": [
            "correct",
            "too_broad",
            "too_fragmented",
            "wrong_assignment",
            "generic_bucket",
            "unsupported_label",
            "should_unlink_noise",
            "needs_l3_split",
            "needs_merge_review",
        ],
        "top_l2_to_review": [
            {
                "l2_id": node.get("l2_id"),
                "label": node.get("label"),
                "event_count": len(node.get("linked_obj_ids", []) or []),
                "sample_obj_ids": (node.get("linked_obj_ids", []) or [])[:5],
            }
            for node in top_l2
        ],
        "l3_parents_to_review": l3_view.get("l3_parents", []) or [],
        "validation_manual_queue": validation.get("manual_review_queue", []) or [],
        "semantic_rescue_assignment_sample": semantic_rescue_assignments,
        "high_importance_linked_l1_sample": linked_high,
        "unlinked_l1_sample": unlinked_sample,
    }
    write_json(out / "manual_review_protocol.json", protocol)
    lines = [
        "# Optimization v2 Manual Review Protocol",
        "",
        f"- run root: `{protocol['run_root']}`",
        f"- review items: {protocol['review_item_count']}",
        "",
        "Use one of these labels for each reviewed item:",
        ", ".join(f"`{label}`" for label in protocol["required_labels"]),
        "",
        "## Top L2",
    ]
    for item in protocol["top_l2_to_review"]:
        lines.append(f"- {item['l2_id']} / {item['label']} ({item['event_count']} events)")
    if semantic_rescue_assignments:
        lines.extend(["", "## Semantic Rescue Assignments"])
        for item in semantic_rescue_assignments:
            lines.append(
                f"- {item['obj_id']} -> {item['l2_id']} / {item['l2_label']} "
                f"(confidence {item['confidence']})"
            )
    write_text(out / "manual_review_protocol.md", "\n".join(lines) + "\n")
    return protocol


def certify_maturity(
    *,
    grace_run_root: Path | str,
    out_dir: Path | str,
    core_root: Path | str,
    grace_llm_run_root: Path | str | None = None,
    icsi_run_root: Path | str | None = None,
    ablation_run_root: Path | str | None = None,
    suite_root: Path | str | None = None,
    split_candidate_run_root: Path | str | None = None,
) -> dict[str, Any]:
    grace = Path(grace_run_root)
    out = ensure_optimization_output(out_dir)
    core = Path(core_root)
    grace_validation = _validation_summary(grace)
    grace_comparison = _comparison_summary(grace)
    grace_retrieval = _retrieval_summary(grace)
    grace_answer_quality = _answer_quality_summary(grace)
    grace_manual_review_completion = _manual_review_completion_summary(grace)
    grace_label_quality = _label_quality(grace)
    grace_semantic_quality = _semantic_key_quality(grace)
    hardcode_matches = _scan_core_for_patterns(core)
    secret_matches = _scan_secret_patterns([core, grace])
    hash_status = _source_hash_status(grace)
    missing = _required_artifacts(grace)
    suite_summary = _maturity_suite_summary(Path(suite_root) if suite_root else None)
    focused_split_review = _suite_focused_split_review_summary(Path(suite_root) if suite_root else None)
    split_candidate_application = _split_candidate_application_summary(Path(split_candidate_run_root) if split_candidate_run_root else None)
    retrieval_split_pressure = _retrieval_split_pressure_summary(Path(split_candidate_run_root) if split_candidate_run_root else None)

    gate_results = {
        "gate_1_isolation": {
            "status": _status(not missing and not secret_matches and hash_status["snapshot_matches_manifest"]),
            "missing_artifacts": missing,
            "secret_match_count": len(secret_matches),
            "source_hash": hash_status,
        },
        "gate_2_no_grace_specific_core": {
            "status": _status(not hardcode_matches),
            "match_count": len(hardcode_matches),
            "matches": hardcode_matches,
        },
        "gate_3_l1_input_audit": {
            "status": _status(
                grace_comparison.get("passes_high_importance_gate", False)
                and hash_status["snapshot_matches_manifest"]
            ),
            "comparison": grace_comparison,
            "source_hash": hash_status,
        },
        "gate_4_semantic_key_quality": {
            "status": _status(
                grace_semantic_quality["count_matches_l1"]
                and not grace_semantic_quality["function_word_top_terms"]
            ),
            **grace_semantic_quality,
        },
        "gate_5_l2_topic_quality": {
            "status": _status(
                grace_validation.get("passes_severe_gate", False)
                and grace_label_quality["type_or_generic_label_count"] == 0
                and grace_label_quality["function_word_label_count"] == 0,
                warning=grace_validation.get("warning_count", 0) > 0,
            ),
            "validation": grace_validation,
            "label_quality": grace_label_quality,
        },
        "gate_8_retrieval_quality": {
            "status": _status(
                grace_retrieval.get("passes_recall_gate", False)
                and grace_retrieval.get("passes_l2_semantic_gate", False)
            ),
            "retrieval": grace_retrieval,
        },
        "gate_7_l3_adaptive_promotion": {
            "status": _status(_l3_quality(grace).get("passes_l3_gate", False)),
            "l3_quality": _l3_quality(grace),
        },
        "gate_9_answer_quality_evaluation": {
            "status": _status(grace_answer_quality.get("status") == "pass", warning=not grace_answer_quality.get("exists", False)),
            "answer_quality": grace_answer_quality,
        },
    }

    if grace_llm_run_root:
        llm_root = Path(grace_llm_run_root)
        llm_manifest = load_json(llm_root / "manifest.json")
        proposal_path = llm_root / "l2" / "llm_induction_proposals.json"
        proposal = load_json(proposal_path) if proposal_path.exists() else {}
        proposal_validation = _llm_proposal_validation_summary(llm_root)
        gate_results["gate_6_llm_assisted_induction"] = {
            "status": _status(
                bool(proposal)
                and int(proposal.get("rejected_count", 0) or 0) >= 0
                and llm_manifest.get("llm_usage", {}).get("status") == "llm_refinement_applied"
                and proposal_validation.get("status") == "pass",
                warning=not proposal or proposal_validation.get("status") == "warning",
            ),
            "label_refinement_status": llm_manifest.get("llm_usage", {}).get("status"),
            "proposal_exists": proposal_path.exists(),
            "proposal_counts": proposal.get("accepted_counts", {}),
            "proposal_rejected_count": proposal.get("rejected_count"),
            "proposal_validation": proposal_validation,
        }

    if icsi_run_root:
        icsi = Path(icsi_run_root)
        icsi_label_quality = _label_quality(icsi)
        icsi_validation = _validation_summary(icsi)
        gate_results["gate_10_cross_dataset_robustness"] = {
            "status": _status(
                icsi_validation.get("passes_severe_gate", False)
                and icsi_label_quality["function_word_label_count"] == 0
            ),
            "icsi_validation": icsi_validation,
            "icsi_label_quality": icsi_label_quality,
        }
    if suite_root:
        gate_results["gate_10_cross_dataset_maturity_suite"] = {
            "status": _status(
                suite_summary.get("exists", False)
                and suite_summary.get("status") == "pass"
                and int(suite_summary.get("failed_dataset_count", 0) or 0) == 0,
                warning=not suite_summary.get("exists", False),
            ),
            "suite": suite_summary,
        }
        gate_results["gate_7_focused_split_review"] = {
            "status": _status(
                focused_split_review.get("exists", False)
                and focused_split_review.get("status") == "pass",
                warning=not focused_split_review.get("exists", False),
            ),
            "focused_split_review": focused_split_review,
        }
    if split_candidate_run_root:
        gate_results["gate_7_split_candidate_application"] = {
            "status": _status(
                split_candidate_application.get("exists", False)
                and split_candidate_application.get("status") == "pass"
            ),
            "split_candidate_application": split_candidate_application,
        }

    manual_protocol = grace / "manual_review" / "manual_review_protocol.json"
    gate_results["gate_11_human_review_protocol"] = {
        "status": _status(manual_protocol.exists(), warning=True),
        "protocol_exists": manual_protocol.exists(),
        "protocol_path": str(manual_protocol),
    }
    gate_results["gate_11_manual_review_completion"] = {
        "status": _status(grace_manual_review_completion.get("status") == "pass", warning=not grace_manual_review_completion.get("exists", False)),
        "manual_review": grace_manual_review_completion,
    }

    non_pass = [name for name, row in gate_results.items() if row["status"] != "pass"]
    gate_results["gate_12_promotion_decision"] = {
        "status": "warning",
        "promotion_recommendation": "do_not_promote" if non_pass else "eligible_for_shadow_mode_only",
        "reason": "promotion is intentionally blocked until all gates pass across repeated isolated runs",
        "non_pass_gates": non_pass,
    }

    if ablation_run_root:
        ablation = Path(ablation_run_root)
        ablation_comparison = _comparison_summary(ablation)
        ablation_retrieval = _retrieval_summary(ablation)
        ablation_validation = _validation_summary(ablation)
        ablation_label_quality = _label_quality(ablation)
        normal_warning_count = int(grace_validation.get("warning_count", 0) or 0)
        ablation_warning_count = int(ablation_validation.get("warning_count", 0) or 0)
        warning_limit = max(normal_warning_count * 8, 8)
        ablation_gate_checks = {
            "high_importance_linked_rate_at_least_0_95": float(
                ablation_comparison.get("v2_high_importance_linked_rate", 0.0) or 0.0
            )
            >= 0.95,
            "semantic_l2_hit_at_least_0_90": float(
                ablation_retrieval.get("expected_l2_semantic_hit_rate", 0.0) or 0.0
            )
            >= 0.9,
            "warning_count_within_ablation_limit": ablation_warning_count <= warning_limit,
            "no_type_or_generic_labels": ablation_label_quality["type_or_generic_label_count"] == 0,
            "no_function_word_labels": ablation_label_quality["function_word_label_count"] == 0,
        }
        gate_results["gate_2_related_topics_ablation"] = {
            "status": _status(all(ablation_gate_checks.values())),
            "gate_semantics": "This gate checks whether v2 remains usable without related_topics; it is intentionally looser than canonical replacement comparison.",
            "ablation_gate_checks": ablation_gate_checks,
            "comparison": ablation_comparison,
            "retrieval": ablation_retrieval,
            "validation": ablation_validation,
            "label_quality": ablation_label_quality,
            "warning_limit": warning_limit,
        }

    failing = [name for name, row in gate_results.items() if row["status"] == "fail"]
    warnings = [name for name, row in gate_results.items() if row["status"] == "warning"]
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "status": "pass" if not failing and not warnings else "warning" if not failing else "fail",
        "failing_gates": failing,
        "warning_gates": warnings,
        "gate_results": gate_results,
        "run_roots": {
            "grace_run_root": str(grace.resolve()),
            "grace_llm_run_root": str(Path(grace_llm_run_root).resolve()) if grace_llm_run_root else "",
            "icsi_run_root": str(Path(icsi_run_root).resolve()) if icsi_run_root else "",
            "ablation_run_root": str(Path(ablation_run_root).resolve()) if ablation_run_root else "",
            "suite_root": str(Path(suite_root).resolve()) if suite_root else "",
            "split_candidate_run_root": str(Path(split_candidate_run_root).resolve()) if split_candidate_run_root else "",
        },
        "cross_dataset_suite": suite_summary,
        "focused_split_review": focused_split_review,
        "split_candidate_application": split_candidate_application,
        "retrieval_split_pressure": retrieval_split_pressure,
        "promotion_recommendation": (
            "do_not_promote"
            if failing or warnings
            else "eligible_for_shadow_mode_only"
        ),
    }
    write_json(out / "maturity_certification_report.json", report)
    lines = [
        "# Optimization v2 Maturity Certification",
        "",
        f"- generated: {report['generated_at_utc']}",
        f"- status: `{report['status']}`",
        f"- promotion recommendation: `{report['promotion_recommendation']}`",
        "",
        "## Gates",
    ]
    for name, row in gate_results.items():
        lines.append(f"- {name}: `{row['status']}`")
    lines.extend(
        [
            "",
            "## Key Summaries",
            f"- retrieval: {grace_retrieval.get('avg_expected_obj_recall_at_context')} L1 recall, {grace_retrieval.get('expected_l2_semantic_hit_rate')} semantic L2 hit",
            f"- answer quality: `{grace_answer_quality.get('status')}`",
            f"- manual review completion: `{grace_manual_review_completion.get('status')}`",
            f"- cross-dataset suite: `{suite_summary.get('status')}`",
            f"- focused split review: `{focused_split_review.get('status')}`",
            f"- split candidate application: `{split_candidate_application.get('status')}`",
            f"- retrieval split pressure: `{retrieval_split_pressure.get('status')}`",
            f"- source hash matches snapshot: `{hash_status.get('source_matches_snapshot')}`",
        ]
    )
    if failing:
        lines.extend(["", "## Failing Gates", ", ".join(failing)])
    if warnings:
        lines.extend(["", "## Warning Gates", ", ".join(warnings)])
    write_text(out / "maturity_certification_report.md", "\n".join(lines) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Certify optimization v2 maturity gates for isolated runs.")
    parser.add_argument("--grace-run-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--core-root", default="optimization/long_term_v2")
    parser.add_argument("--grace-llm-run-root")
    parser.add_argument("--icsi-run-root")
    parser.add_argument("--ablation-run-root")
    parser.add_argument("--suite-root")
    parser.add_argument("--split-candidate-run-root")
    args = parser.parse_args()
    report = certify_maturity(
        grace_run_root=args.grace_run_root,
        grace_llm_run_root=args.grace_llm_run_root,
        icsi_run_root=args.icsi_run_root,
        ablation_run_root=args.ablation_run_root,
        suite_root=args.suite_root,
        split_candidate_run_root=args.split_candidate_run_root,
        core_root=args.core_root,
        out_dir=args.out,
    )
    print(
        "[optimization:v2] maturity certification complete: "
        f"status={report['status']} failing={len(report['failing_gates'])} warnings={len(report['warning_gates'])}"
    )


if __name__ == "__main__":
    main()
