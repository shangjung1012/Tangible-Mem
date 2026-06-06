from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.audit_topic_quality import audit_topic_quality
from optimization.long_term_v2.build_view import build_view
from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text
from optimization.long_term_v2.profiles import load_profile, profile_generic_topic_labels, profile_type_like_labels
from optimization.long_term_v2.validate_view import validate_run


PROFILE_ROOT = REPO_ROOT / "optimization" / "long_term_v2" / "profiles"

_DOMAIN_LEAKAGE_FRAGMENTS = {
    "grace": set(),
    "icsi": {
        "transcript " + "segmentation",
        "idea unit",
        "memory evaluation " + "strategy",
        "manager " + "agent",
        "topic " + "lifecycle",
    },
    "conversation_style": {
        "transcript " + "segmentation",
        "idea unit",
        "memory evaluation " + "strategy",
        "manager " + "agent",
        "topic " + "lifecycle",
        "recording setup",
        "data source",
        "data collection",
        "corpus management",
    },
}


def _iter_l1(tree: dict[str, Any]) -> list[dict[str, Any]]:
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


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _labels(run_root: Path) -> list[str]:
    l2_view = load_json(run_root / "l2" / "l2_view.json")
    labels = [str(node.get("label", "") or "") for node in l2_view.get("l2_nodes", []) or [] if isinstance(node, dict)]
    l3_path = run_root / "l3" / "l3_view.json"
    if l3_path.exists():
        l3_view = load_json(l3_path)
        for parent in l3_view.get("l3_parents", []) or []:
            if not isinstance(parent, dict):
                continue
            labels.append(str(parent.get("label", "") or ""))
            for child in parent.get("child_l2_nodes", []) or []:
                if isinstance(child, dict):
                    labels.append(str(child.get("label", "") or ""))
    return labels


def _generic_bucket_issue_count(labels: list[str], profile_path: Path) -> int:
    profile = load_profile(profile_path)
    generic = profile_generic_topic_labels(profile) | profile_type_like_labels(profile)
    count = 0
    for label in labels:
        clean = label.lower().replace("_", " ").strip()
        parts = clean.split()
        if clean in generic or (len(parts) == 1 and parts and parts[0] in generic):
            count += 1
    return count


def _domain_leakage_issue_count(dataset: str, labels: list[str]) -> int:
    fragments = _DOMAIN_LEAKAGE_FRAGMENTS.get(dataset, set())
    count = 0
    for label in labels:
        clean = label.lower().replace("_", " ")
        if any(fragment in clean for fragment in fragments):
            count += 1
    return count


def _summarize_dataset(*, dataset: str, run_root: Path, profile_path: Path) -> dict[str, Any]:
    manifest = load_json(run_root / "manifest.json")
    tree = load_json(run_root / "input_snapshot" / "tree.json")
    l2_index = load_json(run_root / "l2" / "l2_index.json")
    validation = validate_run(run_root=run_root)
    topic_quality = audit_topic_quality(run_root=run_root)
    labels = _labels(run_root)
    l1_rows = _iter_l1(tree)
    high_ids = {str(row.get("obj_id", "")) for row in l1_rows if _safe_float(row.get("importance")) >= 0.7}
    linked_high = high_ids & set(l2_index)
    high_importance_linked_rate = len(linked_high) / max(1, len(high_ids)) if high_ids else 1.0
    generic_bucket_issue_count = _generic_bucket_issue_count(labels, profile_path)
    domain_leakage_issue_count = _domain_leakage_issue_count(dataset, labels)
    manual_review_issue_count = int(validation.get("manual_review_count", 0)) + int(topic_quality.get("manual_review_count", 0))

    decision = "pass"
    reasons: list[str] = []
    if validation.get("severe_count", 0):
        decision = "fail"
        reasons.append("validation has severe issues")
    if domain_leakage_issue_count:
        decision = "fail"
        reasons.append("domain leakage labels detected")
    if generic_bucket_issue_count:
        decision = "warning" if decision == "pass" else decision
        reasons.append("generic or type-like labels need review")
    if high_importance_linked_rate < 0.90:
        decision = "warning" if decision == "pass" else decision
        reasons.append("high-importance linked rate below 0.90")
    if not reasons:
        reasons.append("no severe validation, generic collapse, or domain leakage detected")

    return {
        "dataset": dataset,
        "run_root": str(run_root.resolve()),
        "l1_count": int(manifest.get("source_l1_count", 0)),
        "l2_count": int(manifest.get("l2_topic_count", 0)),
        "l3_count": int(manifest.get("l3_parent_count", 0)),
        "high_importance_linked_rate": round(high_importance_linked_rate, 4),
        "review_only_l1_count": int(manifest.get("unlinked_l1_count", 0)),
        "generic_bucket_issue_count": generic_bucket_issue_count,
        "domain_leakage_issue_count": domain_leakage_issue_count,
        "manual_review_issue_count": manual_review_issue_count,
        "decision": decision,
        "reason": "; ".join(reasons),
    }


def _dataset_specs(
    *,
    grace_share_mem_root: Path,
    icsi_share_mem_root: Path,
    conversation_share_mem_root: Path,
) -> list[dict[str, Any]]:
    return [
        {
            "dataset": "grace",
            "share_mem_root": grace_share_mem_root,
            "profile": PROFILE_ROOT / "mentor_mentee.yaml",
        },
        {
            "dataset": "icsi",
            "share_mem_root": icsi_share_mem_root,
            "profile": PROFILE_ROOT / "isci_meeting.yaml",
        },
        {
            "dataset": "conversation_style",
            "share_mem_root": conversation_share_mem_root,
            "profile": PROFILE_ROOT / "conversation_memory.yaml",
        },
    ]


def run_cross_dataset_suite(
    *,
    grace_share_mem_root: Path | str,
    icsi_share_mem_root: Path | str,
    conversation_share_mem_root: Path | str,
    out_root: Path | str,
    mode: str = "deterministic",
    clean: bool = False,
) -> dict[str, Any]:
    out = ensure_optimization_output(out_root)
    if clean and out.exists():
        shutil.rmtree(out)
        out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for spec in _dataset_specs(
        grace_share_mem_root=Path(grace_share_mem_root),
        icsi_share_mem_root=Path(icsi_share_mem_root),
        conversation_share_mem_root=Path(conversation_share_mem_root),
    ):
        dataset = spec["dataset"]
        run_root = out / dataset
        build_view(
            share_mem_root=spec["share_mem_root"],
            profile_path=spec["profile"],
            out_root=run_root,
            mode=mode,
            clean=True,
        )
        rows.append(_summarize_dataset(dataset=dataset, run_root=run_root, profile_path=spec["profile"]))

    suite_decision = "pass"
    if any(row["decision"] == "fail" for row in rows):
        suite_decision = "fail"
    elif any(row["decision"] == "warning" for row in rows):
        suite_decision = "warning"
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "mode": mode,
        "decision": suite_decision,
        "datasets": rows,
    }
    write_json(out / "suite_summary.json", report)
    write_text(
        out / "suite_summary.md",
        "\n".join(
            [
                "# Optimization v2 Cross-Dataset Suite",
                "",
                f"- decision: `{suite_decision}`",
                f"- datasets: {len(rows)}",
                "",
                "| Dataset | Decision | L1 | L2 | L3 | High importance linked | Leakage | Reason |",
                "|---|---:|---:|---:|---:|---:|---:|---|",
                *[
                    "| {dataset} | {decision} | {l1_count} | {l2_count} | {l3_count} | {high_importance_linked_rate} | {domain_leakage_issue_count} | {reason} |".format(
                        **row
                    )
                    for row in rows
                ],
                "",
            ]
        ),
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run optimization v2 cross-dataset demonstration suite.")
    parser.add_argument("--grace-share-mem-root", required=True)
    parser.add_argument("--icsi-share-mem-root", required=True)
    parser.add_argument("--conversation-share-mem-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=["deterministic", "llm-assisted"], default="deterministic")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    report = run_cross_dataset_suite(
        grace_share_mem_root=args.grace_share_mem_root,
        icsi_share_mem_root=args.icsi_share_mem_root,
        conversation_share_mem_root=args.conversation_share_mem_root,
        out_root=args.out,
        mode=args.mode,
        clean=args.clean,
    )
    print(f"[optimization:v2] cross-dataset suite complete: decision={report['decision']} out={args.out}")


if __name__ == "__main__":
    main()
