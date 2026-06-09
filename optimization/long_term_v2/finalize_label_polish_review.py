from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text


SUPPRESS_L2_LABELS = {"go ahead", "did", "didn", "know", "two"}
RELABEL_L2 = {
    "time": "time allocation and overlap analysis",
    "bug": "adaptation count failure",
    "file": "file storage and reorganization",
}
RELABEL_CHILD = {
    "data per": "speaker adaptation data volume",
    "probably form here": "test set form review",
}


def _copy_run(source: Path, out: Path, *, clean: bool) -> Path:
    target = ensure_optimization_output(out)
    if source.resolve() == target.resolve() or source.resolve() in target.resolve().parents:
        raise ValueError("label polish candidate output root must be separate from source run root")
    if target.exists() and clean:
        shutil.rmtree(target)
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"label polish candidate output root is not empty: {target}")
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def _load_review_items(review_root: Path) -> list[dict[str, Any]]:
    payload = load_json(review_root / "label_polish_review_queue.json")
    return [row for row in payload.get("items", []) or [] if isinstance(row, dict)]


def _decision_for_item(item: dict[str, Any]) -> dict[str, Any]:
    label = " ".join(str(item.get("label") or "").strip().lower().split())
    if item.get("item_type") == "child_l2_topic" and label in RELABEL_CHILD:
        return {
            **item,
            "decision": "relabel_child_l2",
            "new_label": RELABEL_CHILD[label],
            "severity": "none",
            "reason": "Weak generated child label is replaced with an evidence-backed noun phrase.",
        }
    if label in SUPPRESS_L2_LABELS:
        return {
            **item,
            "decision": "suppress_from_effective_l2",
            "new_label": "",
            "severity": "none",
            "reason": "Label is discourse/filler-like or too ambiguous to remain a durable L2 topic.",
        }
    if label in RELABEL_L2:
        return {
            **item,
            "decision": "relabel_l2",
            "new_label": RELABEL_L2[label],
            "severity": "none",
            "reason": "Short label is replaced with a more specific evidence-backed noun phrase.",
        }
    return {
        **item,
        "decision": "manual_review_required",
        "new_label": "",
        "severity": "warning",
        "reason": "No safe deterministic sidecar decision is available for this label.",
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _apply_l2_changes(candidate: Path, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    l2_view_path = candidate / "l2" / "l2_view.json"
    l2_index_path = candidate / "l2" / "l2_index.json"
    if not l2_view_path.exists():
        return []
    l2_view = load_json(l2_view_path)
    l2_index = load_json(l2_index_path) if l2_index_path.exists() else {}
    relabels = {
        str(row.get("l2_id") or ""): str(row.get("new_label") or "")
        for row in decisions
        if row.get("decision") == "relabel_l2" and row.get("new_label")
    }
    applied: list[dict[str, Any]] = []
    for node in l2_view.get("l2_nodes", []) or []:
        l2_id = str(node.get("l2_id") or "")
        if l2_id not in relabels:
            continue
        old_label = str(node.get("label") or "")
        node["label"] = relabels[l2_id]
        node["label_polish"] = {
            "source": "label_polish_finalization",
            "previous_label": old_label,
            "new_label": relabels[l2_id],
            "sidecar_only": True,
        }
        applied.append({"l2_id": l2_id, "previous_label": old_label, "new_label": relabels[l2_id]})
    for assignment in l2_index.values():
        if isinstance(assignment, dict):
            l2_id = str(assignment.get("l2_id") or "")
            if l2_id in relabels:
                assignment["l2_label"] = relabels[l2_id]
                assignment["label_polish_source"] = "label_polish_finalization"
    write_json(l2_view_path, l2_view)
    write_json(l2_index_path, l2_index)
    return applied


def _apply_child_changes(candidate: Path, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    l3_view_path = candidate / "l3" / "l3_view.json"
    l3_index_path = candidate / "l3" / "l3_index.json"
    if not l3_view_path.exists():
        return []
    l3_view = load_json(l3_view_path)
    l3_index = load_json(l3_index_path) if l3_index_path.exists() else {}
    relabels = {
        str(row.get("child_l2_id") or row.get("l2_id") or ""): str(row.get("new_label") or "")
        for row in decisions
        if row.get("decision") == "relabel_child_l2" and row.get("new_label")
    }
    applied: list[dict[str, Any]] = []
    for parent in l3_view.get("l3_parents", []) or []:
        for child in parent.get("child_l2_nodes", []) or []:
            child_id = str(child.get("child_l2_id") or child.get("l2_id") or "")
            if child_id not in relabels:
                continue
            old_label = str(child.get("label") or "")
            child["label"] = relabels[child_id]
            child["label_polish"] = {
                "source": "label_polish_finalization",
                "previous_label": old_label,
                "new_label": relabels[child_id],
                "sidecar_only": True,
            }
            applied.append({"child_l2_id": child_id, "previous_label": old_label, "new_label": relabels[child_id]})
    for assignment in l3_index.values():
        if isinstance(assignment, dict):
            child_id = str(assignment.get("child_l2_id") or "")
            if child_id in relabels:
                assignment["child_l2_label"] = relabels[child_id]
                assignment["label_polish_source"] = "label_polish_finalization"
    write_json(l3_view_path, l3_view)
    write_json(l3_index_path, l3_index)
    return applied


def _update_effective_topic_index(candidate: Path, decisions: list[dict[str, Any]]) -> dict[str, Any]:
    path = candidate / "topic_review" / "effective_topic_index.json"
    existing = load_json(path) if path.exists() else {}
    suppressed = {
        str(l2_id)
        for l2_id in existing.get("suppressed_l2_ids", []) or []
        if str(l2_id)
    }
    suppressed.update(
        str(row.get("l2_id") or "")
        for row in decisions
        if row.get("decision") == "suppress_from_effective_l2" and str(row.get("l2_id") or "")
    )
    payload = {
        **existing,
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "suppressed_l2_ids": sorted(suppressed),
        "label_polish_source": "label_polish_finalization",
        "note": "Effective topic sidecar only. Raw L1/L2/L3 source artifacts are preserved in the source run.",
    }
    write_json(path, payload)
    return payload


def finalize_label_polish_review(
    *,
    source_run_root: Path | str,
    review_root: Path | str,
    out_run_root: Path | str,
    clean: bool = False,
) -> dict[str, Any]:
    source = Path(source_run_root)
    review = Path(review_root)
    candidate = _copy_run(source, Path(out_run_root), clean=clean)
    items = _load_review_items(review)
    decisions = [_decision_for_item(item) for item in items]
    _write_jsonl(review / "review_decisions.jsonl", decisions)
    applied_l2 = _apply_l2_changes(candidate, decisions)
    applied_child = _apply_child_changes(candidate, decisions)
    effective = _update_effective_topic_index(candidate, decisions)
    unresolved = [row for row in decisions if row["decision"] == "manual_review_required"]
    newly_suppressed = sorted(
        str(row.get("l2_id") or "")
        for row in decisions
        if row.get("decision") == "suppress_from_effective_l2" and str(row.get("l2_id") or "")
    )
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "decision": "label_polish_finalized" if not unresolved else "label_polish_manual_review_needed",
        "source_run_root": str(source.resolve()),
        "candidate_run_root": str(candidate.resolve()),
        "review_root": str(review.resolve()),
        "decision_count": len(decisions),
        "unresolved_count": len(unresolved),
        "newly_suppressed_l2_ids": newly_suppressed,
        "suppressed_l2_ids": effective.get("suppressed_l2_ids", []),
        "applied_l2_relabels": applied_l2,
        "applied_child_relabels": applied_child,
        "decisions": decisions,
        "canonical_mutation": False,
    }
    write_json(review / "final_label_polish_report.json", report)
    write_text(review / "final_label_polish_report.md", _format_md(report))
    write_json(candidate / "label_polish" / "final_label_polish_report.json", report)
    return report


def _format_md(report: dict[str, Any]) -> str:
    lines = [
        "# Final Label Polish Report",
        "",
        f"- decision: `{report['decision']}`",
        f"- decisions: `{report['decision_count']}`",
        f"- unresolved: `{report['unresolved_count']}`",
        f"- newly suppressed L2: `{len(report.get('newly_suppressed_l2_ids', []))}`",
        f"- total effective suppressed L2: `{len(report['suppressed_l2_ids'])}`",
        f"- candidate run: `{report['candidate_run_root']}`",
        "",
        "## Applied Relabels",
        "",
    ]
    for row in report["applied_l2_relabels"]:
        lines.append(f"- L2 `{row['l2_id']}`: `{row['previous_label']}` -> `{row['new_label']}`")
    for row in report["applied_child_relabels"]:
        lines.append(f"- child `{row['child_l2_id']}`: `{row['previous_label']}` -> `{row['new_label']}`")
    if not report["applied_l2_relabels"] and not report["applied_child_relabels"]:
        lines.append("- none")
    lines.extend(["", "## Newly Suppressed L2", ""])
    if report.get("newly_suppressed_l2_ids"):
        lines.extend(f"- `{l2_id}`" for l2_id in report["newly_suppressed_l2_ids"])
    else:
        lines.append("- none")
    lines.extend(["", "## Total Effective Suppressed L2", ""])
    if report["suppressed_l2_ids"]:
        lines.extend(f"- `{l2_id}`" for l2_id in report["suppressed_l2_ids"])
    else:
        lines.append("- none")
    lines.extend(["", "Raw source run artifacts were not modified."])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize label polish review into an isolated candidate run.")
    parser.add_argument("--source-run-root", required=True)
    parser.add_argument("--review-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    report = finalize_label_polish_review(
        source_run_root=args.source_run_root,
        review_root=args.review_root,
        out_run_root=args.out,
        clean=args.clean,
    )
    print(
        "[optimization:v2] label polish finalized: "
        f"decision={report['decision']} newly_suppressed={len(report.get('newly_suppressed_l2_ids', []))} "
        f"total_suppressed={len(report['suppressed_l2_ids'])} "
        f"candidate={report['candidate_run_root']}"
    )


if __name__ == "__main__":
    main()
