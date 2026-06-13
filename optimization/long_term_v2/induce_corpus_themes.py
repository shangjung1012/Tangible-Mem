from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text
from optimization.long_term_v2.review_l3_children import _extract_json, _response_text, _usage_metadata
from optimization.long_term_v2.text_utils import slugify


GENERIC_THEME_LABELS = {
    "data",
    "discussion",
    "evaluation",
    "memory",
    "method",
    "model",
    "process",
    "project",
    "system",
    "topic",
}


def _iter_l1(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for meeting in tree.get("meetings", []) or []:
        if not isinstance(meeting, dict):
            continue
        meeting_id = str(meeting.get("meeting_id", "") or "")
        meeting_date = str(meeting.get("meeting_date", "") or "")
        for obj in meeting.get("memory_objects", []) or []:
            if not isinstance(obj, dict):
                continue
            obj_id = str(obj.get("obj_id", "") or "")
            if obj_id:
                rows[obj_id] = {**obj, "meeting_id": meeting_id, "meeting_date": meeting_date}
    return rows


def _compact_text(value: str, *, max_chars: int = 260) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= max_chars else text[: max_chars - 14].rstrip() + "...(truncated)"


def _l2_payload(node: dict[str, Any], l1_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    linked_ids = [str(obj_id) for obj_id in node.get("linked_obj_ids", []) or [] if str(obj_id)]
    representative: list[dict[str, Any]] = []
    for obj_id in linked_ids[:4]:
        obj = l1_index.get(obj_id, {})
        representative.append(
            {
                "obj_id": obj_id,
                "meeting_id": obj.get("meeting_id", ""),
                "type": obj.get("type", ""),
                "importance": obj.get("importance", 0.0),
                "content": _compact_text(str(obj.get("content", "") or "")),
            }
        )
    return {
        "l2_id": str(node.get("l2_id", "") or ""),
        "label": str(node.get("label", "") or ""),
        "definition": _compact_text(str(node.get("definition", "") or ""), max_chars=220),
        "event_count": len(linked_ids),
        "meeting_count": len(node.get("meeting_ids", []) or []),
        "top_semantic_terms": node.get("top_semantic_terms", [])[:8],
        "representative_l1": representative,
    }


def _build_prompt(l2_topics: list[dict[str, Any]]) -> str:
    payload = {
        "task": "Induce corpus-level L3 theme families from evidence-backed L2 topics.",
        "goal": (
            "Group multiple L2 topics into higher-level research-meeting themes. "
            "The themes should name durable research problems or workflows, not merely frequent terms."
        ),
        "rules": [
            "Use only the provided L2 summaries and representative L1 snippets.",
            "Do not use any hardcoded project ontology.",
            "A theme should usually group at least two L2 topics that share a research problem, method evolution, or workflow.",
            "Do not invent L2 ids or L1 ids.",
            "Prefer concise English noun phrases.",
            "Return JSON only.",
        ],
        "l2_topics": l2_topics,
        "response_schema": {
            "themes": [
                {
                    "label": "corpus-level theme label",
                    "definition": "what long-running research problem or workflow this theme represents",
                    "inclusion_criteria": ["evidence that belongs here"],
                    "exclusion_criteria": ["nearby evidence that does not belong here"],
                    "supporting_l2_ids": ["existing L2 id"],
                    "representative_l1_ids": ["existing L1 id from supporting L2 topics"],
                    "confidence": 0.0,
                    "rationale": "why these L2 topics form one L3 family",
                }
            ]
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _theme_rows_from_parsed(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    rows = parsed.get("themes", []) or parsed.get("reviews", []) or []
    if not isinstance(rows, list):
        return []
    flattened: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        nested = row.get("themes")
        if isinstance(nested, list) and not row.get("label"):
            flattened.extend(nested_row for nested_row in nested if isinstance(nested_row, dict))
        else:
            flattened.append(row)
    return flattened


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _validate_theme(row: dict[str, Any], *, l2_by_id: dict[str, dict[str, Any]], l1_to_l2: dict[str, str]) -> dict[str, Any]:
    label = " ".join(str(row.get("label", "") or "").strip().lower().split())
    supporting_l2_ids = _as_list(row.get("supporting_l2_ids"))
    representative_l1_ids = _as_list(row.get("representative_l1_ids"))
    errors: list[str] = []
    if not label:
        errors.append("missing_label")
    if label in GENERIC_THEME_LABELS:
        errors.append("generic_label")
    unknown_l2_ids = [l2_id for l2_id in supporting_l2_ids if l2_id not in l2_by_id]
    if unknown_l2_ids:
        errors.append("unknown_l2_ids")
    if len(set(supporting_l2_ids) - set(unknown_l2_ids)) < 2:
        errors.append("insufficient_supporting_l2")
    allowed_l1_ids = {
        obj_id
        for l2_id in supporting_l2_ids
        for obj_id in (l2_by_id.get(l2_id, {}).get("linked_obj_ids", []) or [])
    }
    unknown_l1_ids = [obj_id for obj_id in representative_l1_ids if obj_id not in l1_to_l2]
    out_of_theme_l1_ids = [obj_id for obj_id in representative_l1_ids if obj_id in l1_to_l2 and obj_id not in allowed_l1_ids]
    valid_representative_l1_ids = [obj_id for obj_id in representative_l1_ids if obj_id in allowed_l1_ids]
    warnings: list[str] = []
    if unknown_l1_ids:
        warnings.append("pruned_unknown_l1_ids")
    if out_of_theme_l1_ids:
        warnings.append("pruned_representative_l1_outside_supporting_l2")
    if not valid_representative_l1_ids:
        errors.append("missing_valid_representative_l1")
    try:
        confidence = float(row.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
        errors.append("invalid_confidence")
    if confidence < 0 or confidence > 1:
        errors.append("invalid_confidence")
    rationale = str(row.get("rationale", "") or "").strip()
    if not rationale:
        errors.append("missing_rationale")
    return {
        "label": label,
        "definition": str(row.get("definition", "") or "").strip(),
        "inclusion_criteria": _as_list(row.get("inclusion_criteria")),
        "exclusion_criteria": _as_list(row.get("exclusion_criteria")),
        "supporting_l2_ids": supporting_l2_ids,
        "representative_l1_ids": valid_representative_l1_ids,
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "rationale": rationale,
        "validation_warnings": sorted(set(warnings)),
        "validation_errors": sorted(set(errors)),
    }


def _build_theme_view(
    accepted: list[dict[str, Any]],
    *,
    l2_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], int]:
    parents: list[dict[str, Any]] = []
    index: dict[str, Any] = {}
    duplicate_assignment_count = 0
    for theme in accepted:
        l3_id = f"L3-{slugify(theme['label'])}"
        child_nodes: list[dict[str, Any]] = []
        linked_union: list[str] = []
        for l2_id in theme["supporting_l2_ids"]:
            node = l2_by_id.get(l2_id)
            if not node:
                continue
            linked = [str(obj_id) for obj_id in node.get("linked_obj_ids", []) or [] if str(obj_id)]
            linked_union.extend(linked)
            child_nodes.append(
                {
                    "child_l2_id": l2_id,
                    "label": str(node.get("label", "") or ""),
                    "source": "optimization_v2_corpus_theme_child_l2",
                    "linked_obj_ids": linked,
                    "event_count": len(linked),
                    "definition": node.get("definition", ""),
                    "current_state": node.get("current_state", ""),
                    "timeline_digest": node.get("timeline_digest", [])[:8],
                }
            )
            for obj_id in linked:
                if obj_id in index:
                    duplicate_assignment_count += 1
                    continue
                index[obj_id] = {
                    "parent_l3_id": l3_id,
                    "parent_l3_label": theme["label"],
                    "child_l2_id": l2_id,
                    "child_l2_label": str(node.get("label", "") or ""),
                    "source": "optimization_v2_corpus_theme_induction",
                }
        parents.append(
            {
                "l3_id": l3_id,
                "label": theme["label"],
                "source": "optimization_v2_corpus_theme_induction",
                "definition": theme["definition"],
                "inclusion_criteria": theme["inclusion_criteria"],
                "exclusion_criteria": theme["exclusion_criteria"],
                "supporting_l2_ids": theme["supporting_l2_ids"],
                "representative_l1_ids": theme["representative_l1_ids"],
                "linked_obj_ids": sorted(set(linked_union)),
                "child_l2_nodes": child_nodes,
                "confidence": theme["confidence"],
                "rationale": theme["rationale"],
                "metrics": {
                    "supporting_l2_count": len(child_nodes),
                    "linked_l1_count": len(set(linked_union)),
                },
            }
        )
    return (
        {
            "schema_version": 1,
            "generated_at_utc": utc_now_iso(),
            "source": "optimization_v2_corpus_theme_induction",
            "l3_parents": parents,
        },
        dict(sorted(index.items())),
        duplicate_assignment_count,
    )


def _summary_markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Corpus Theme Induction Summary",
            "",
            f"- L2 topics considered: `{summary.get('l2_topic_count', 0)}`",
            f"- accepted themes: `{summary.get('accepted_theme_count', 0)}`",
            f"- rejected themes: `{summary.get('rejected_theme_count', 0)}`",
            f"- invalid themes: `{summary.get('invalid_theme_count', 0)}`",
            f"- duplicate L1 assignment count: `{summary.get('duplicate_assignment_count', 0)}`",
            "",
            "This is a sidecar-only corpus-level L3 proposal. It does not modify raw L1, raw L2, or raw L3.",
            "",
        ]
    )


def induce_corpus_themes(
    *,
    run_root: Path | str,
    model: str = "gemini-2.5-pro",
    client: Any | None = None,
    max_l2_topics: int = 80,
    clean: bool = False,
) -> dict[str, Any]:
    root = Path(run_root)
    ensure_optimization_output(root)
    l3_dir = root / "l3"
    api_dir = root / "api_calls" / "corpus_theme_induction"
    if clean:
        for path in [
            l3_dir / "corpus_theme_proposals.json",
            l3_dir / "corpus_theme_rejected.json",
            l3_dir / "corpus_theme_view.json",
            l3_dir / "corpus_theme_index.json",
            l3_dir / "corpus_theme_summary.json",
            l3_dir / "corpus_theme_summary.md",
        ]:
            if path.exists():
                path.unlink()
        if api_dir.exists():
            shutil.rmtree(api_dir)
    api_dir.mkdir(parents=True, exist_ok=True)
    l2_view = load_json(root / "l2" / "l2_view.json")
    tree = load_json(root / "input_snapshot" / "tree.json")
    l1_index = _iter_l1(tree)
    l2_nodes = [node for node in l2_view.get("l2_nodes", []) or [] if isinstance(node, dict)]
    l2_nodes = sorted(l2_nodes, key=lambda node: (-len(node.get("linked_obj_ids", []) or []), str(node.get("label", ""))))[:max_l2_topics]
    l2_by_id = {str(node.get("l2_id", "") or ""): node for node in l2_nodes if str(node.get("l2_id", "") or "")}
    l1_to_l2 = {
        str(obj_id): l2_id
        for l2_id, node in l2_by_id.items()
        for obj_id in (node.get("linked_obj_ids", []) or [])
        if str(obj_id)
    }
    payload = [_l2_payload(node, l1_index) for node in l2_nodes]
    prompt = _build_prompt(payload)
    if client is None:
        from share_mem.l1.gemini_clients import create_gemini_client

        client = create_gemini_client()
    start = time.perf_counter()
    raw_text = ""
    parsed: dict[str, Any] = {"themes": []}
    usage_metadata: dict[str, Any] = {}
    error = ""
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        raw_text = _response_text(response)
        usage_metadata = _usage_metadata(response)
        parsed = _extract_json(raw_text)
    except Exception as exc:  # pragma: no cover - exercised by real API failures
        error = f"{type(exc).__name__}: {exc}"
    theme_rows = _theme_rows_from_parsed(parsed)
    validated = [_validate_theme(row, l2_by_id=l2_by_id, l1_to_l2=l1_to_l2) for row in theme_rows]
    accepted = [row for row in validated if not row["validation_errors"]]
    rejected = [row for row in validated if row["validation_errors"]]
    theme_view, theme_index, duplicate_assignment_count = _build_theme_view(accepted, l2_by_id=l2_by_id)
    latency_ms = round((time.perf_counter() - start) * 1000, 3)
    write_json(
        api_dir / "0001_corpus_theme_induction.json",
        {
            "schema_version": 1,
            "created_at_utc": utc_now_iso(),
            "stage": "corpus_theme_induction",
            "model": model,
            "l2_topic_ids": [row["l2_id"] for row in payload],
            "prompt": prompt,
            "raw_response": raw_text,
            "parsed_json": parsed,
            "latency_ms": latency_ms,
            "usage_metadata": usage_metadata,
            "error": error,
        },
    )
    write_json(l3_dir / "corpus_theme_proposals.json", {"accepted_themes": accepted})
    write_json(l3_dir / "corpus_theme_rejected.json", {"rejected_themes": rejected})
    write_json(l3_dir / "corpus_theme_view.json", theme_view)
    write_json(l3_dir / "corpus_theme_index.json", theme_index)
    summary = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "model": model,
        "l2_topic_count": len(l2_nodes),
        "accepted_theme_count": len(accepted),
        "rejected_theme_count": len(rejected),
        "invalid_theme_count": len(rejected),
        "duplicate_assignment_count": duplicate_assignment_count,
        "latency_ms": latency_ms,
        "errors": [error] if error else [],
        "outputs": {
            "corpus_theme_view": str((l3_dir / "corpus_theme_view.json").resolve()),
            "corpus_theme_index": str((l3_dir / "corpus_theme_index.json").resolve()),
        },
    }
    write_json(l3_dir / "corpus_theme_summary.json", summary)
    write_text(l3_dir / "corpus_theme_summary.md", _summary_markdown(summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Induce corpus-level L3 theme sidecars from optimization v2 L2 topics.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--model", default="gemini-2.5-pro")
    parser.add_argument("--max-l2-topics", type=int, default=80)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    summary = induce_corpus_themes(
        run_root=args.run_root,
        model=args.model,
        max_l2_topics=args.max_l2_topics,
        clean=args.clean,
    )
    print(
        "[optimization:v2] corpus theme induction complete: "
        f"accepted={summary['accepted_theme_count']} rejected={summary['rejected_theme_count']}"
    )


if __name__ == "__main__":
    main()
