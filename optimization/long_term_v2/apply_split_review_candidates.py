from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text
from optimization.long_term_v2.text_utils import slugify, tokens


def _copy_run(*, source: Path, target: Path, clean: bool) -> None:
    out = ensure_optimization_output(target)
    source_resolved = source.resolve()
    target_resolved = out.resolve()
    if source_resolved == target_resolved or source_resolved in target_resolved.parents:
        raise ValueError("candidate output root must not be the source run root or inside it")
    if out.exists() and clean:
        shutil.rmtree(out)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"candidate output root is not empty: {out}")
    shutil.copytree(source, out, dirs_exist_ok=True)


def _event_text(event: dict[str, Any]) -> str:
    return " ".join(str(event.get(field, "") or "") for field in ("summary", "content", "evidence"))


def _child_specs(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    children = proposal.get("child_candidates", []) or []
    specs: list[dict[str, Any]] = []
    if children:
        for child in children:
            label = str(child.get("label", "") or "").strip().lower()
            if not label:
                continue
            specs.append(
                {
                    "label": label,
                    "assignment_criteria": [
                        str(value).strip().lower()
                        for value in child.get("assignment_criteria", []) or []
                        if str(value).strip()
                    ],
                    "representative_l1_ids": [
                        str(value)
                        for value in child.get("representative_l1_ids", []) or []
                        if str(value)
                    ],
                }
            )
        return specs
    return [
        {"label": str(label).strip().lower(), "assignment_criteria": [str(label).strip().lower()], "representative_l1_ids": []}
        for label in proposal.get("proposed_child_labels", []) or []
        if str(label).strip()
    ]


def _assign_events(events: list[dict[str, Any]], child_specs: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    label_tokens = [
        set(tokens(" ".join([spec["label"], *spec.get("assignment_criteria", [])])))
        for spec in child_specs
    ]
    representative_to_child: dict[str, int] = {}
    for child_index, spec in enumerate(child_specs):
        for obj_id in spec.get("representative_l1_ids", []) or []:
            representative_to_child.setdefault(str(obj_id), child_index)
    assignments: list[list[dict[str, Any]]] = [[] for _ in child_specs]
    for index, event in enumerate(events):
        obj_id = str(event.get("obj_id", "") or "")
        if obj_id in representative_to_child:
            assignments[representative_to_child[obj_id]].append(event)
            continue
        event_text = _event_text(event).lower()
        event_tokens = set(tokens(event_text))
        scores: list[tuple[int, int]] = []
        for label_index, spec in enumerate(child_specs):
            label = spec["label"]
            score = len(event_tokens & label_tokens[label_index])
            if label.lower() in event_text:
                score += max(2, len(label_tokens[label_index]))
            for criterion in spec.get("assignment_criteria", []) or []:
                if criterion and criterion in event_text:
                    score += max(2, len(tokens(criterion)))
            scores.append((score, label_index))
        best_score, best_label_index = max(scores, key=lambda row: (row[0], -row[1]))
        if best_score <= 0:
            best_label_index = index % len(child_specs)
        assignments[best_label_index].append(event)
    return assignments


def _separability_failure(assignments: list[list[dict[str, Any]]]) -> dict[str, Any] | None:
    counts = [len(rows) for rows in assignments]
    total = sum(counts)
    if total == 0:
        return {"reason": "empty_source_timeline", "child_sizes": counts}
    non_empty = sum(1 for count in counts if count > 0)
    max_count = max(counts) if counts else 0
    if non_empty < 2:
        return {"reason": "low_assignment_separability", "child_sizes": counts}
    if any(0 < count < 3 for count in counts):
        return {"reason": "tiny_candidate_child", "child_sizes": counts}
    if max_count > 35:
        return {"reason": "candidate_child_still_oversized", "child_sizes": counts}
    return None


def _child_node(
    *,
    source_l2_id: str,
    parent_l3_id: str,
    child_spec: dict[str, Any],
    events: list[dict[str, Any]],
    proposal: dict[str, Any],
) -> dict[str, Any]:
    label = child_spec["label"]
    child_id = f"{source_l2_id}-split-{slugify(label)}"
    latest = events[-1].get("summary", "") if events else ""
    return {
        "child_l2_id": child_id,
        "label": label,
        "parent_l3_id": parent_l3_id,
        "source_l2_id": source_l2_id,
        "split_source": "llm_focused_split_review_candidate",
        "assignment_criteria": child_spec.get("assignment_criteria", []) or [label],
        "linked_obj_ids": [str(event.get("obj_id", "") or "") for event in events if event.get("obj_id")],
        "event_count": len(events),
        "timeline_digest": events,
        "current_state": (
            f"Candidate child topic '{label}' has {len(events)} assigned L1 evidence object(s). "
            f"Latest evidence: {str(latest)[:220]}"
        ),
        "confidence": proposal.get("confidence", 0.0),
        "proposal_rationale": proposal.get("rationale", ""),
        "representative_l1_ids": child_spec.get("representative_l1_ids", []),
    }


def apply_split_review_candidates(
    *,
    source_run_root: Path | str,
    out_root: Path | str,
    clean: bool = False,
) -> dict[str, Any]:
    source = Path(source_run_root)
    out = Path(out_root)
    _copy_run(source=source, target=out, clean=clean)

    l2_view = load_json(out / "l2" / "l2_view.json")
    l3_view = load_json(out / "l3" / "l3_view.json") if (out / "l3" / "l3_view.json").exists() else {"l3_parents": []}
    l3_index = load_json(out / "l3" / "l3_index.json") if (out / "l3" / "l3_index.json").exists() else {}
    merge_review = (
        load_json(out / "l3" / "l2_merge_review.json")
        if (out / "l3" / "l2_merge_review.json").exists()
        else {"schema_version": 1, "merge_reviews": []}
    )
    proposals = load_json(out / "l2" / "llm_split_review_proposals.json")

    l2_by_id = {str(node.get("l2_id", "")): node for node in l2_view.get("l2_nodes", []) or []}
    accepted = [row for row in proposals.get("accepted_split_candidates", []) or [] if isinstance(row, dict)]
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    parents = [
        parent
        for parent in l3_view.get("l3_parents", []) or []
        if str(parent.get("source_l2_id", "")) not in {str(row.get("source_l2_id", "")) for row in accepted}
    ]
    for proposal in accepted:
        source_l2_id = str(proposal.get("source_l2_id", "") or "")
        node = l2_by_id.get(source_l2_id)
        child_specs = _child_specs(proposal)
        if not node:
            skipped.append({"source_l2_id": source_l2_id, "reason": "source_l2_not_found"})
            continue
        if len(child_specs) < 2:
            skipped.append({"source_l2_id": source_l2_id, "reason": "insufficient_child_labels"})
            continue
        events = list(node.get("timeline_digest", []) or [])
        if not events:
            skipped.append({"source_l2_id": source_l2_id, "reason": "source_l2_has_no_timeline"})
            continue
        parent_l3_id = f"L3-{slugify(node.get('label', source_l2_id))}-candidate-split"
        assignments = _assign_events(events, child_specs)
        separability_failure = _separability_failure(assignments)
        if separability_failure:
            skipped.append(
                {
                    "source_l2_id": source_l2_id,
                    "reason": separability_failure["reason"],
                    "child_sizes": separability_failure["child_sizes"],
                }
            )
            continue
        children = [
            _child_node(
                source_l2_id=source_l2_id,
                parent_l3_id=parent_l3_id,
                child_spec=child_spec,
                events=assignments[index],
                proposal=proposal,
            )
            for index, child_spec in enumerate(child_specs)
        ]
        for obj_id in node.get("linked_obj_ids", []) or []:
            l3_index.pop(str(obj_id), None)
        for child in children:
            for obj_id in child["linked_obj_ids"]:
                l3_index[obj_id] = {
                    "parent_l3_id": parent_l3_id,
                    "parent_l3_label": node.get("label", ""),
                    "child_l2_id": child["child_l2_id"],
                    "child_l2_label": child["label"],
                    "split_source": "llm_focused_split_review_candidate",
                }
        parents.append(
            {
                "l3_id": parent_l3_id,
                "label": node.get("label", ""),
                "source_l2_id": source_l2_id,
                "promotion_reason": {
                    "reason_codes": ["llm_focused_split_review_candidate"],
                    "proposal_confidence": proposal.get("confidence"),
                    "proposal_rationale": proposal.get("rationale", ""),
                },
                "child_l2_nodes": children,
                "confidence": proposal.get("confidence", 0.0),
            }
        )
        applied.append(
            {
                "source_l2_id": source_l2_id,
                "parent_l3_id": parent_l3_id,
                "child_count": len(children),
                "assigned_l1_count": sum(len(child["linked_obj_ids"]) for child in children),
                "child_sizes": {child["label"]: len(child["linked_obj_ids"]) for child in children},
            }
        )

    applied_sources = {row["source_l2_id"] for row in applied}
    retained_reviews = [
        row
        for row in merge_review.get("merge_reviews", []) or []
        if not (row.get("action") == "needs_split_review" and row.get("source_l2_id") in applied_sources)
    ]
    for parent in parents:
        if parent.get("source_l2_id") not in applied_sources:
            continue
        for child in parent.get("child_l2_nodes", []) or []:
            count = len(child.get("linked_obj_ids", []) or [])
            if count < 3:
                retained_reviews.append(
                    {
                        "parent_l3_id": parent.get("l3_id", ""),
                        "source_child_l2_id": child.get("child_l2_id", ""),
                        "source_child_l2_label": child.get("label", ""),
                        "source_event_count": count,
                        "action": "needs_merge_review",
                        "reason_codes": ["too_few_l1_nodes"],
                    }
                )
            if count > 35:
                retained_reviews.append(
                    {
                        "parent_l3_id": parent.get("l3_id", ""),
                        "source_child_l2_id": child.get("child_l2_id", ""),
                        "source_child_l2_label": child.get("label", ""),
                        "source_event_count": count,
                        "action": "needs_split_review",
                        "reason_codes": ["candidate_child_still_oversized"],
                    }
                )

    l3_view["l3_parents"] = parents
    write_json(out / "l3" / "l3_view.json", l3_view)
    write_json(out / "l3" / "l3_index.json", dict(sorted(l3_index.items())))
    merge_review["merge_reviews"] = retained_reviews
    write_json(out / "l3" / "l2_merge_review.json", merge_review)
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "status": "candidate_splits_applied" if applied else "no_candidate_splits_applied",
        "source_run_root": str(source.resolve()),
        "candidate_run_root": str(out.resolve()),
        "applied_split_count": len(applied),
        "skipped_split_count": len(skipped),
        "applied_splits": applied,
        "skipped_splits": skipped,
    }
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        manifest["l3_parent_count"] = len(parents)
        manifest["l3_assigned_l1_count"] = len(l3_index)
        manifest["split_review_candidate"] = {
            "source_run_root": str(source.resolve()),
            "applied_split_count": len(applied),
            "skipped_split_count": len(skipped),
            "generated_at_utc": report["generated_at_utc"],
        }
        write_json(manifest_path, manifest)
    write_json(out / "l3" / "applied_split_review_candidates.json", report)
    write_text(out / "l3" / "applied_split_review_candidates.md", _format_report_md(report))
    return report


def _format_report_md(report: dict[str, Any]) -> str:
    lines = [
        "# Applied Split Review Candidates",
        "",
        f"- status: `{report.get('status')}`",
        f"- applied split count: {report.get('applied_split_count')}",
        f"- skipped split count: {report.get('skipped_split_count')}",
        "",
    ]
    for row in report.get("applied_splits", []) or []:
        lines.append(
            f"- {row.get('source_l2_id')} -> {row.get('parent_l3_id')} "
            f"({row.get('assigned_l1_count')} assigned L1, children={row.get('child_sizes')})"
        )
    if report.get("skipped_splits"):
        lines.extend(["", "## Skipped"])
        for row in report.get("skipped_splits", []) or []:
            lines.append(f"- {row.get('source_l2_id')}: {row.get('reason')}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply accepted focused split-review proposals to a candidate-only optimization run.")
    parser.add_argument("--source-run-root", required=True)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    report = apply_split_review_candidates(
        source_run_root=args.source_run_root,
        out_root=args.out_root,
        clean=args.clean,
    )
    print(
        "[optimization:v2] split-review candidate application complete: "
        f"status={report['status']} applied={report['applied_split_count']} skipped={report['skipped_split_count']}"
    )


if __name__ == "__main__":
    main()
