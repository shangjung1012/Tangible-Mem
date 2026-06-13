from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text


ALLOWED_DECISIONS = {"keep", "relabel", "reject_split", "needs_human_review"}
SCORE_FIELDS = ("coherence_score", "label_support_score", "specificity_score", "confidence")


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text is not None:
        return str(text)
    if isinstance(response, dict):
        return str(response.get("text", ""))
    return str(response)


def _usage_metadata(response: Any) -> dict[str, Any]:
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None and isinstance(response, dict):
        metadata = response.get("usage_metadata")
    if metadata is None:
        return {}
    if hasattr(metadata, "model_dump"):
        try:
            return dict(metadata.model_dump())
        except Exception:
            return {}
    if isinstance(metadata, dict):
        return metadata
    output: dict[str, Any] = {}
    for name in ("prompt_token_count", "candidates_token_count", "total_token_count", "thoughts_token_count"):
        value = getattr(metadata, name, None)
        if value is not None:
            output[name] = value
    return output


def _extract_json(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        object_start = text.find("{")
        object_end = text.rfind("}")
        array_start = text.find("[")
        array_end = text.rfind("]")
        if array_start >= 0 and array_end > array_start and (object_start < 0 or array_start < object_start):
            parsed = json.loads(text[array_start : array_end + 1])
        elif object_start >= 0 and object_end > object_start:
            parsed = json.loads(text[object_start : object_end + 1])
        else:
            raise
    if isinstance(parsed, list):
        return {"reviews": parsed}
    if not isinstance(parsed, dict):
        raise ValueError("L3 child review response must be a JSON object or array.")
    return parsed


def _review_rows_from_parsed(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    rows = parsed.get("reviews", []) or []
    if not isinstance(rows, list):
        return []
    flattened: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        nested = row.get("reviews")
        if isinstance(nested, list) and not row.get("child_l2_id"):
            flattened.extend(nested_row for nested_row in nested if isinstance(nested_row, dict))
        else:
            flattened.append(row)
    return flattened


def _tree_l1_index(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
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
            if not obj_id:
                continue
            rows[obj_id] = {**obj, "meeting_id": meeting_id, "meeting_date": meeting_date}
    return rows


def _child_rows(l3_view: dict[str, Any], l1_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for parent in l3_view.get("l3_parents", []) or []:
        if not isinstance(parent, dict):
            continue
        for child in parent.get("child_l2_nodes", []) or []:
            if not isinstance(child, dict):
                continue
            rows.append(_compact_child(parent, child, l1_index))
    return rows


def _compact_child(parent: dict[str, Any], child: dict[str, Any], l1_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    child_ids = [str(obj_id) for obj_id in child.get("linked_obj_ids", []) or [] if str(obj_id)]
    representative_ids: list[str] = []
    for event in child.get("timeline_digest", []) or []:
        obj_id = str(event.get("obj_id", "") or "") if isinstance(event, dict) else ""
        if obj_id and obj_id in l1_index and obj_id not in representative_ids:
            representative_ids.append(obj_id)
        if len(representative_ids) >= 4:
            break
    for obj_id in child_ids:
        if obj_id in l1_index and obj_id not in representative_ids:
            representative_ids.append(obj_id)
        if len(representative_ids) >= 6:
            break
    representative_l1 = []
    for obj_id in representative_ids:
        obj = l1_index[obj_id]
        representative_l1.append(
            {
                "obj_id": obj_id,
                "meeting_id": obj.get("meeting_id", ""),
                "type": obj.get("type", ""),
                "importance": obj.get("importance", 0.0),
                "content": str(obj.get("content", "") or "")[:320],
            }
        )
    return {
        "parent_l3_id": str(parent.get("l3_id", "") or ""),
        "parent_l3_label": str(parent.get("label", "") or ""),
        "source_l2_id": str(parent.get("source_l2_id", "") or ""),
        "child_l2_id": str(child.get("child_l2_id", "") or ""),
        "old_label": str(child.get("label", "") or ""),
        "child_l1_count": len(child_ids),
        "child_linked_obj_ids": child_ids,
        "representative_l1": representative_l1,
    }


def _build_prompt(children: list[dict[str, Any]]) -> str:
    payload = {
        "task": "Review L3 child topics for an evidence-grounded long-term memory system.",
        "instructions": [
            "Use only the provided representative L1 content.",
            "Do not invent a child topic that is not supported by the L1 evidence.",
            "Judge whether each child is coherent and whether the label names the evidence.",
            "Prefer concise English noun phrases for relabel decisions.",
            "If the evidence is mixed or the child is not a coherent subtopic, choose reject_split or needs_human_review.",
            "Return JSON only.",
        ],
        "children": children,
        "response_schema": {
            "reviews": [
                {
                    "parent_l3_id": "same id from input",
                    "parent_l3_label": "same label from input",
                    "child_l2_id": "same id from input",
                    "old_label": "same label from input",
                    "decision": "keep | relabel | reject_split | needs_human_review",
                    "new_label": "required only for relabel, otherwise empty string",
                    "definition": "one sentence explaining the child topic",
                    "inclusion_criteria": ["what belongs in this child"],
                    "exclusion_criteria": ["what does not belong in this child"],
                    "supporting_l1_ids": ["L1 ids from the provided child evidence"],
                    "off_topic_l1_ids": ["provided L1 ids that do not fit, if any"],
                    "coherence_score": 0.0,
                    "label_support_score": 0.0,
                    "specificity_score": 0.0,
                    "confidence": 0.0,
                    "rationale": "short evidence-backed reason",
                }
            ]
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0.0 or number > 1.0:
        return None
    return number


def _fallback_review(child: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "parent_l3_id": child["parent_l3_id"],
        "parent_l3_label": child["parent_l3_label"],
        "child_l2_id": child["child_l2_id"],
        "old_label": child["old_label"],
        "decision": "needs_human_review",
        "new_label": "",
        "definition": "",
        "inclusion_criteria": [],
        "exclusion_criteria": [],
        "supporting_l1_ids": [],
        "off_topic_l1_ids": [],
        "coherence_score": 0.0,
        "label_support_score": 0.0,
        "specificity_score": 0.0,
        "confidence": 0.0,
        "rationale": reason,
        "validation_errors": [reason],
        "validation_status": "invalid_fallback",
    }


def _validate_review(row: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    errors: list[str] = []
    child_ids = set(child.get("child_linked_obj_ids", []) or [])
    child_id = str(output.get("child_l2_id", "") or "")
    decision = str(output.get("decision", "") or "")
    if child_id != child["child_l2_id"]:
        errors.append("child_l2_id_mismatch")
    if str(output.get("parent_l3_id", "") or "") != child["parent_l3_id"]:
        errors.append("parent_l3_id_mismatch")
    if decision not in ALLOWED_DECISIONS:
        errors.append("invalid_decision")
    if decision == "relabel" and not str(output.get("new_label", "") or "").strip():
        errors.append("missing_new_label_for_relabel")
    if not str(output.get("rationale", "") or "").strip():
        errors.append("missing_rationale")
    supporting = [str(value) for value in output.get("supporting_l1_ids", []) or [] if str(value)]
    off_topic = [str(value) for value in output.get("off_topic_l1_ids", []) or [] if str(value)]
    if any(obj_id not in child_ids for obj_id in supporting):
        errors.append("supporting_l1_id_not_in_child")
    if any(obj_id not in child_ids for obj_id in off_topic):
        errors.append("off_topic_l1_id_not_in_child")
    if decision in {"keep", "relabel"}:
        required_support = min(2, len(child_ids))
        if len(set(supporting)) < required_support:
            errors.append("insufficient_supporting_l1_ids")
    for field in SCORE_FIELDS:
        number = _safe_float(output.get(field))
        if number is None:
            errors.append(f"invalid_{field}")
            output[field] = 0.0
        else:
            output[field] = round(number, 3)
    for field in ("definition", "new_label", "rationale"):
        output[field] = str(output.get(field, "") or "")
    for field in ("inclusion_criteria", "exclusion_criteria"):
        output[field] = [str(value) for value in output.get(field, []) or [] if str(value).strip()]
    output["supporting_l1_ids"] = supporting
    output["off_topic_l1_ids"] = off_topic
    output["parent_l3_label"] = str(output.get("parent_l3_label", "") or child["parent_l3_label"])
    output["old_label"] = str(output.get("old_label", "") or child["old_label"])
    if errors:
        fallback = _fallback_review(child, ";".join(sorted(set(errors))))
        fallback["original_llm_row"] = row
        return fallback
    output["validation_errors"] = []
    output["validation_status"] = "valid"
    return output


def _reviews_by_child(parsed_reviews: list[dict[str, Any]], children: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    parsed_by_id = {
        str(row.get("child_l2_id", "") or ""): row
        for row in parsed_reviews
        if isinstance(row, dict) and str(row.get("child_l2_id", "") or "")
    }
    reviews: dict[str, dict[str, Any]] = {}
    for child in children:
        row = parsed_by_id.get(child["child_l2_id"])
        if row is None:
            reviews[child["child_l2_id"]] = _fallback_review(child, "missing_llm_review")
        else:
            reviews[child["child_l2_id"]] = _validate_review(row, child)
    return reviews


def _with_review_metadata(child: dict[str, Any], review: dict[str, Any], *, label: str) -> dict[str, Any]:
    row = deepcopy(child)
    row["source_label"] = child.get("label", "")
    row["label"] = label
    row["review_status"] = review["decision"]
    row["review_confidence"] = review.get("confidence", 0.0)
    row["review_rationale"] = review.get("rationale", "")
    if review.get("definition"):
        row["definition"] = review["definition"]
    if review.get("inclusion_criteria"):
        row["inclusion_criteria"] = review["inclusion_criteria"]
    if review.get("exclusion_criteria"):
        row["exclusion_criteria"] = review["exclusion_criteria"]
    return row


def _build_effective_l3(l3_view: dict[str, Any], reviews: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    effective = deepcopy(l3_view)
    effective["source"] = "optimization_long_term_v2_l3_child_review"
    effective["review_generated_at_utc"] = utc_now_iso()
    effective_index: dict[str, Any] = {}
    for parent in effective.get("l3_parents", []) or []:
        accepted: list[dict[str, Any]] = []
        review_only: list[dict[str, Any]] = []
        for child in parent.get("child_l2_nodes", []) or []:
            child_id = str(child.get("child_l2_id", "") or "")
            review = reviews.get(child_id) or _fallback_review(
                {
                    "parent_l3_id": parent.get("l3_id", ""),
                    "parent_l3_label": parent.get("label", ""),
                    "child_l2_id": child_id,
                    "old_label": child.get("label", ""),
                    "child_linked_obj_ids": child.get("linked_obj_ids", []) or [],
                },
                "missing_review_at_effective_build",
            )
            decision = review.get("decision")
            if decision == "keep":
                effective_child = _with_review_metadata(child, review, label=str(child.get("label", "") or ""))
                accepted.append(effective_child)
                _index_child(effective_index, parent, effective_child, review)
            elif decision == "relabel":
                effective_child = _with_review_metadata(child, review, label=str(review.get("new_label", "") or ""))
                accepted.append(effective_child)
                _index_child(effective_index, parent, effective_child, review)
            else:
                review_child = _with_review_metadata(child, review, label=str(child.get("label", "") or ""))
                review_only.append(review_child)
                _index_parent_only(effective_index, parent, child, review)
        parent["child_l2_nodes"] = accepted
        parent["review_only_child_l2_nodes"] = review_only
    return effective, dict(sorted(effective_index.items()))


def _index_child(index: dict[str, Any], parent: dict[str, Any], child: dict[str, Any], review: dict[str, Any]) -> None:
    for obj_id in child.get("linked_obj_ids", []) or []:
        index[str(obj_id)] = {
            "parent_l3_id": parent.get("l3_id", ""),
            "parent_l3_label": parent.get("label", ""),
            "child_l2_id": child.get("child_l2_id", ""),
            "child_l2_label": child.get("label", ""),
            "source_child_l2_label": child.get("source_label", child.get("label", "")),
            "review_status": review.get("decision", ""),
        }


def _index_parent_only(index: dict[str, Any], parent: dict[str, Any], child: dict[str, Any], review: dict[str, Any]) -> None:
    for obj_id in child.get("linked_obj_ids", []) or []:
        index[str(obj_id)] = {
            "parent_l3_id": parent.get("l3_id", ""),
            "parent_l3_label": parent.get("label", ""),
            "child_l2_id": "",
            "child_l2_label": "",
            "source_child_l2_id": child.get("child_l2_id", ""),
            "source_child_l2_label": child.get("label", ""),
            "review_status": review.get("decision", ""),
        }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _summary_markdown(summary: dict[str, Any]) -> str:
    decision_counts = summary.get("decision_counts", {})
    lines = [
        "# L3 Child Label Review Summary",
        "",
        f"- child count: {summary.get('child_count', 0)}",
        f"- API calls: {summary.get('api_call_count', 0)}",
        f"- model: `{summary.get('model', '')}`",
        f"- invalid review count: {summary.get('invalid_review_count', 0)}",
        "",
        "## Decisions",
        "",
    ]
    for decision in sorted(ALLOWED_DECISIONS):
        lines.append(f"- {decision}: {decision_counts.get(decision, 0)}")
    lines.append("")
    return "\n".join(lines)


def _clean_sidecars(root: Path) -> None:
    for path in [
        root / "l3" / "l3_child_label_review.jsonl",
        root / "l3" / "l3_child_label_review_summary.json",
        root / "l3" / "l3_child_label_review_summary.md",
        root / "l3" / "effective_l3_view.json",
        root / "l3" / "effective_l3_index.json",
    ]:
        if path.exists():
            path.unlink()
    api_dir = root / "api_calls" / "l3_child_review"
    if api_dir.exists():
        shutil.rmtree(api_dir)


def review_l3_children(
    *,
    run_root: Path | str,
    batch_size: int = 12,
    model: str = "",
    client: Any | None = None,
    clean: bool = False,
) -> dict[str, Any]:
    root = ensure_optimization_output(run_root)
    if clean:
        _clean_sidecars(root)
    l3_dir = root / "l3"
    api_dir = root / "api_calls" / "l3_child_review"
    api_dir.mkdir(parents=True, exist_ok=True)
    l3_view = load_json(l3_dir / "l3_view.json")
    tree = load_json(root / "input_snapshot" / "tree.json")
    l1_index = _tree_l1_index(tree)
    children = _child_rows(l3_view, l1_index)
    selected_model = model or os.getenv("GEMINI_MODEL", "").strip() or "gemini-2.5-pro"
    if client is None:
        from share_mem.l1.gemini_clients import create_gemini_client

        client = create_gemini_client()
    batches = [
        children[index : index + max(1, batch_size)]
        for index in range(0, len(children), max(1, batch_size))
    ]
    all_reviews: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    start = time.perf_counter()
    for batch_index, batch in enumerate(batches, start=1):
        prompt = _build_prompt(batch)
        batch_start = time.perf_counter()
        raw_text = ""
        parsed: dict[str, Any] = {}
        usage_metadata: dict[str, Any] = {}
        error = ""
        try:
            response = client.models.generate_content(
                model=selected_model,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            raw_text = _response_text(response)
            usage_metadata = _usage_metadata(response)
            parsed = _extract_json(raw_text)
            parsed_reviews = _review_rows_from_parsed(parsed)
            all_reviews.update(_reviews_by_child(parsed_reviews, batch))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            errors.append(f"batch {batch_index}: {error}")
            for child in batch:
                all_reviews[child["child_l2_id"]] = _fallback_review(child, error)
        latency_ms = round((time.perf_counter() - batch_start) * 1000, 3)
        write_json(
            api_dir / f"{batch_index:04d}_l3_child_review.json",
            {
                "schema_version": 1,
                "created_at_utc": utc_now_iso(),
                "stage": "l3_child_label_review",
                "batch_index": batch_index,
                "batch_count": len(batches),
                "batch_child_l2_ids": [child["child_l2_id"] for child in batch],
                "model": selected_model,
                "prompt": prompt,
                "raw_response": raw_text,
                "parsed_json": parsed,
                "latency_ms": latency_ms,
                "usage_metadata": usage_metadata,
                "error": error,
            },
        )
    ordered_reviews = [all_reviews[child["child_l2_id"]] for child in children]
    effective_l3_view, effective_l3_index = _build_effective_l3(l3_view, all_reviews)
    _write_jsonl(l3_dir / "l3_child_label_review.jsonl", ordered_reviews)
    write_json(l3_dir / "effective_l3_view.json", effective_l3_view)
    write_json(l3_dir / "effective_l3_index.json", effective_l3_index)
    decision_counts = {decision: 0 for decision in sorted(ALLOWED_DECISIONS)}
    for review in ordered_reviews:
        decision_counts[str(review.get("decision", "needs_human_review"))] = decision_counts.get(str(review.get("decision", "")), 0) + 1
    summary = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "model": selected_model,
        "batch_size": batch_size,
        "api_call_count": len(batches),
        "child_count": len(children),
        "reviewed_child_l2_ids": [child["child_l2_id"] for child in children],
        "decision_counts": decision_counts,
        "invalid_review_count": sum(1 for review in ordered_reviews if review.get("validation_errors")),
        "latency_ms": round((time.perf_counter() - start) * 1000, 3),
        "errors": errors,
        "outputs": {
            "review_jsonl": str((l3_dir / "l3_child_label_review.jsonl").resolve()),
            "effective_l3_view": str((l3_dir / "effective_l3_view.json").resolve()),
            "effective_l3_index": str((l3_dir / "effective_l3_index.json").resolve()),
        },
    }
    write_json(l3_dir / "l3_child_label_review_summary.json", summary)
    write_text(l3_dir / "l3_child_label_review_summary.md", _summary_markdown(summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Review optimization v2 L3 child labels and write effective L3 sidecars.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--model", default="")
    parser.add_argument("--review-mode", choices=["all-children"], default="all-children")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    report = review_l3_children(
        run_root=args.run_root,
        batch_size=args.batch_size,
        model=args.model,
        clean=args.clean,
    )
    print(
        "[optimization:v2] l3 child review complete: "
        f"children={report['child_count']} api_calls={report['api_call_count']} "
        f"decisions={report['decision_counts']}"
    )


if __name__ == "__main__":
    main()
