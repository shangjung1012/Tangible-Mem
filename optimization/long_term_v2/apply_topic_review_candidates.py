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


def _copy_run(source: Path, out: Path, *, clean: bool) -> Path:
    target = ensure_optimization_output(out)
    if source.resolve() == target.resolve() or source.resolve() in target.resolve().parents:
        raise ValueError("candidate output root must be separate from source run root")
    if target.exists() and clean:
        shutil.rmtree(target)
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"candidate output root is not empty: {target}")
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def _proposal_list(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
    if not payload:
        return []
    return [row for row in payload.get(key, []) or [] if isinstance(row, dict)]


def _apply_label_refinements(out: Path, label_candidates: dict[str, Any] | None) -> list[dict[str, Any]]:
    proposals = _proposal_list(label_candidates, "proposals")
    if not proposals:
        return []
    l2_view = load_json(out / "l2" / "l2_view.json")
    l2_index = load_json(out / "l2" / "l2_index.json") if (out / "l2" / "l2_index.json").exists() else {}
    l3_view = load_json(out / "l3" / "l3_view.json") if (out / "l3" / "l3_view.json").exists() else {"l3_parents": []}
    l3_index = load_json(out / "l3" / "l3_index.json") if (out / "l3" / "l3_index.json").exists() else {}
    applied: list[dict[str, Any]] = []
    by_id = {str(row.get("source_l2_id", "") or ""): row for row in proposals}
    for node in l2_view.get("l2_nodes", []) or []:
        if not isinstance(node, dict):
            continue
        proposal = by_id.get(str(node.get("l2_id", "") or ""))
        if not proposal:
            continue
        new_label = str(proposal.get("proposed_label", "") or "").strip()
        if not new_label:
            continue
        old_label = str(node.get("label", "") or "")
        node["label"] = new_label
        node["definition"] = f"Evidence-backed topic about {new_label}."
        node["label_refinement"] = {
            "source": "active_l2_review_candidate",
            "previous_label": old_label,
            "proposal_id": proposal.get("proposal_id", ""),
            "representative_l1_ids": proposal.get("representative_l1_ids", []),
            "review_required": True,
        }
        applied.append({"source_l2_id": node.get("l2_id"), "previous_label": old_label, "new_label": new_label})
    relabel_by_l2 = {row["source_l2_id"]: row["new_label"] for row in applied}
    for assignment in l2_index.values():
        if isinstance(assignment, dict):
            l2_id = str(assignment.get("l2_id", "") or "")
            if l2_id in relabel_by_l2:
                assignment["l2_label"] = relabel_by_l2[l2_id]
                assignment["label_refinement_source"] = "active_l2_review_candidate"
    for parent in l3_view.get("l3_parents", []) or []:
        if not isinstance(parent, dict):
            continue
        source_l2_id = str(parent.get("source_l2_id", "") or "")
        if source_l2_id in relabel_by_l2:
            parent["label"] = relabel_by_l2[source_l2_id]
    for assignment in l3_index.values():
        if isinstance(assignment, dict):
            source_l2_id = str(assignment.get("source_l2_id", "") or "")
            if source_l2_id in relabel_by_l2:
                assignment["parent_l3_label"] = relabel_by_l2[source_l2_id]
    write_json(out / "l2" / "l2_view.json", l2_view)
    write_json(out / "l2" / "l2_index.json", l2_index)
    write_json(out / "l3" / "l3_view.json", l3_view)
    write_json(out / "l3" / "l3_index.json", l3_index)
    return applied


def _score_event(event: dict[str, Any], child: dict[str, Any]) -> int:
    event_tokens = set(tokens(str(event.get("summary", "") or "")))
    child_tokens = set(tokens(" ".join([str(child.get("label", "") or ""), *[str(value) for value in child.get("assignment_criteria", []) or []]])))
    return len(event_tokens & child_tokens)


def _assign_children(events: list[dict[str, Any]], children: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = [[] for _ in children]
    representative_to_child: dict[str, int] = {}
    for index, child in enumerate(children):
        for obj_id in child.get("representative_l1_ids", []) or []:
            representative_to_child.setdefault(str(obj_id), index)
    for index, event in enumerate(events):
        obj_id = str(event.get("obj_id", "") or "")
        if obj_id in representative_to_child:
            groups[representative_to_child[obj_id]].append(event)
            continue
        scores = [(_score_event(event, child), child_index) for child_index, child in enumerate(children)]
        score, child_index = max(scores, key=lambda row: (row[0], -row[1]))
        if score <= 0:
            child_index = index % len(children)
        groups[child_index].append(event)
    return groups


def _split_is_valid(groups: list[list[dict[str, Any]]]) -> bool:
    counts = [len(group) for group in groups]
    if sum(1 for count in counts if count > 0) < 2:
        return False
    if any(0 < count < 3 for count in counts):
        return False
    return True


def _apply_split_candidates(out: Path, split_candidates: dict[str, Any] | None) -> list[dict[str, Any]]:
    proposals = _proposal_list(split_candidates, "split_candidates")
    if not proposals:
        return []
    l2_view = load_json(out / "l2" / "l2_view.json")
    l3_view = load_json(out / "l3" / "l3_view.json") if (out / "l3" / "l3_view.json").exists() else {"l3_parents": []}
    l3_index = load_json(out / "l3" / "l3_index.json") if (out / "l3" / "l3_index.json").exists() else {}
    l2_by_id = {str(node.get("l2_id", "") or ""): node for node in l2_view.get("l2_nodes", []) or [] if isinstance(node, dict)}
    applied: list[dict[str, Any]] = []
    for proposal in proposals:
        if proposal.get("application_policy") == "sidecar_review_required":
            continue
        source_l2_id = str(proposal.get("source_l2_id", "") or "")
        node = l2_by_id.get(source_l2_id)
        children = [child for child in proposal.get("child_candidates", []) or [] if isinstance(child, dict)]
        if not node or len(children) < 2:
            continue
        events = [event for event in node.get("timeline_digest", []) or [] if isinstance(event, dict)]
        groups = _assign_children(events, children)
        if not _split_is_valid(groups):
            continue
        parent_l3_id = f"L3-{slugify(str(node.get('label', '') or source_l2_id))}-review-candidate"
        child_nodes: list[dict[str, Any]] = []
        for child, group in zip(children, groups):
            label = str(child.get("label", "") or "").strip()
            child_l2_id = f"{source_l2_id}-review-{slugify(label)}"
            linked = [str(event.get("obj_id", "") or "") for event in group if str(event.get("obj_id", "") or "")]
            child_node = {
                "child_l2_id": child_l2_id,
                "label": label,
                "parent_l3_id": parent_l3_id,
                "source_l2_id": source_l2_id,
                "linked_obj_ids": linked,
                "event_count": len(linked),
                "timeline_digest": group,
                "assignment_criteria": child.get("assignment_criteria", []) or [label],
                "split_source": "active_l2_review_candidate",
                "review_required": True,
            }
            child_nodes.append(child_node)
            for obj_id in linked:
                l3_index[obj_id] = {
                    "parent_l3_id": parent_l3_id,
                    "parent_l3_label": str(node.get("label", "") or ""),
                    "child_l2_id": child_l2_id,
                    "child_l2_label": label,
                    "source_l2_id": source_l2_id,
                    "split_source": "active_l2_review_candidate",
                }
        l3_view.setdefault("l3_parents", []).append(
            {
                "l3_id": parent_l3_id,
                "label": str(node.get("label", "") or ""),
                "source_l2_id": source_l2_id,
                "promotion_reason": {"reason_codes": ["active_l2_review_candidate"], "review_required": True},
                "child_l2_nodes": child_nodes,
                "confidence": proposal.get("confidence", 0.0),
            }
        )
        applied.append(
            {
                "source_l2_id": source_l2_id,
                "parent_l3_id": parent_l3_id,
                "child_count": len(child_nodes),
                "assigned_l1_count": sum(len(child["linked_obj_ids"]) for child in child_nodes),
                "child_sizes": {child["label"]: len(child["linked_obj_ids"]) for child in child_nodes},
            }
        )
    write_json(out / "l3" / "l3_view.json", l3_view)
    write_json(out / "l3" / "l3_index.json", l3_index)
    return applied


def apply_topic_review_candidates(
    *,
    source_run_root: Path | str,
    label_candidates: dict[str, Any] | None,
    split_candidates: dict[str, Any] | None,
    out_root: Path | str,
    clean: bool = False,
) -> dict[str, Any]:
    source = Path(source_run_root)
    out = _copy_run(source, Path(out_root), clean=clean)
    applied_labels = _apply_label_refinements(out, label_candidates)
    applied_splits = _apply_split_candidates(out, split_candidates)
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "source_run_root": str(source.resolve()),
        "candidate_run_root": str(out.resolve()),
        "applied_label_refinement_count": len(applied_labels),
        "applied_split_count": len(applied_splits),
        "applied_label_refinements": applied_labels,
        "applied_splits": applied_splits,
        "status": "candidate_written",
    }
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        manifest["topic_review_candidate"] = {
            "source_run_root": str(source.resolve()),
            "applied_label_refinement_count": len(applied_labels),
            "applied_split_count": len(applied_splits),
            "generated_at_utc": report["generated_at_utc"],
        }
        if (out / "l3" / "l3_view.json").exists():
            manifest["l3_parent_count"] = len(load_json(out / "l3" / "l3_view.json").get("l3_parents", []) or [])
        if (out / "l3" / "l3_index.json").exists():
            manifest["l3_assigned_l1_count"] = len(load_json(out / "l3" / "l3_index.json"))
        write_json(manifest_path, manifest)
    write_json(out / "topic_review_candidate" / "applied_topic_review_candidates.json", report)
    write_text(out / "topic_review_candidate" / "applied_topic_review_candidates.md", _format_md(report))
    return report


def _format_md(report: dict[str, Any]) -> str:
    lines = [
        "# Applied Topic Review Candidates",
        "",
        f"- status: `{report['status']}`",
        f"- label refinements: `{report['applied_label_refinement_count']}`",
        f"- split candidates: `{report['applied_split_count']}`",
        "",
    ]
    for row in report["applied_label_refinements"]:
        lines.append(f"- relabel `{row['source_l2_id']}`: `{row['previous_label']}` -> `{row['new_label']}`")
    for row in report["applied_splits"]:
        lines.append(f"- split `{row['source_l2_id']}` -> `{row['parent_l3_id']}` children={row['child_sizes']}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply sidecar label/split review candidates into an isolated optimization candidate run.")
    parser.add_argument("--source-run-root", required=True)
    parser.add_argument("--label-candidates", required=True)
    parser.add_argument("--split-candidates", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    report = apply_topic_review_candidates(
        source_run_root=args.source_run_root,
        label_candidates=load_json(args.label_candidates),
        split_candidates=load_json(args.split_candidates),
        out_root=args.out,
        clean=args.clean,
    )
    print(
        "[optimization:v2] topic review candidate written: "
        f"labels={report['applied_label_refinement_count']} splits={report['applied_split_count']}"
    )


if __name__ == "__main__":
    main()
