from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json
from optimization.long_term_v2.llm_topic_refinement import _extract_json, _response_text, _usage_metadata
from optimization.long_term_v2.profiles import load_profile


def _compact_l2_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "l2_id": node.get("l2_id", ""),
        "label": node.get("label", ""),
        "event_count": len(node.get("linked_obj_ids", []) or []),
        "representative_l1_ids": node.get("representative_l1_ids", [])[:5],
        "top_semantic_terms": node.get("top_semantic_terms", [])[:8],
        "timeline": [
            {
                "obj_id": row.get("obj_id", ""),
                "meeting_id": row.get("meeting_id", ""),
                "summary": str(row.get("summary", "") or "")[:220],
            }
            for row in (node.get("timeline_digest", []) or [])[:5]
        ],
    }


def _build_prompt(l2_nodes: list[dict[str, Any]], profile: dict[str, Any]) -> str:
    payload = {
        "task": "Review evidence-induced L2 topics and propose merge, split, or assignment-review candidates. Do not rewrite the source data.",
        "constraints": [
            "Use only the provided topic labels, semantic terms, and representative L1 evidence summaries.",
            "Every proposal must cite representative_l1_ids from the provided topic payload.",
            "Prefer no proposal over speculative proposals.",
            "Do not propose Grace-specific taxonomy unless the evidence shown here supports it.",
            "Return JSON only.",
        ],
        "profile": {
            "domain": profile.get("domain", ""),
            "topic_key_language": profile.get("topic_key_language", ""),
        },
        "topics": [_compact_l2_node(node) for node in l2_nodes],
        "response_schema": {
            "merge_candidates": [
                {
                    "source_l2_id": "existing id",
                    "target_l2_id": "existing id",
                    "confidence": 0.0,
                    "rationale": "why these should be reviewed for merge",
                    "representative_l1_ids": ["obj ids from source or target topic"],
                }
            ],
            "split_candidates": [
                {
                    "source_l2_id": "existing id",
                    "proposed_child_labels": ["short noun phrase"],
                    "confidence": 0.0,
                    "rationale": "why this topic should be reviewed for split",
                    "representative_l1_ids": ["obj ids from source topic"],
                }
            ],
            "assignment_concerns": [
                {
                    "obj_id": "existing obj id",
                    "l2_id": "existing id",
                    "confidence": 0.0,
                    "rationale": "why this assignment should be reviewed",
                }
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _valid_representatives(ids: list[Any], allowed: set[str]) -> list[str]:
    return [str(value) for value in ids or [] if str(value) in allowed]


def _validate_proposals(parsed: dict[str, Any], l2_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    l2_by_id = {str(node.get("l2_id", "")): node for node in l2_nodes}
    obj_to_l2 = {
        str(obj_id): str(node.get("l2_id", ""))
        for node in l2_nodes
        for obj_id in (node.get("linked_obj_ids", []) or [])
    }
    accepted = {"merge_candidates": [], "split_candidates": [], "assignment_concerns": []}
    rejected: list[dict[str, Any]] = []

    for row in parsed.get("merge_candidates", []) or []:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source_l2_id", "") or "")
        target = str(row.get("target_l2_id", "") or "")
        confidence = _safe_float(row.get("confidence"))
        allowed_ids = set(l2_by_id.get(source, {}).get("linked_obj_ids", []) or []) | set(
            l2_by_id.get(target, {}).get("linked_obj_ids", []) or []
        )
        reps = _valid_representatives(row.get("representative_l1_ids", []), allowed_ids)
        if source in l2_by_id and target in l2_by_id and source != target and confidence >= 0.5 and reps:
            accepted["merge_candidates"].append({**row, "representative_l1_ids": reps})
        else:
            rejected.append({"proposal_type": "merge_candidate", "proposal": row, "reason": "invalid_reference_or_low_confidence"})

    for row in parsed.get("split_candidates", []) or []:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source_l2_id", "") or "")
        confidence = _safe_float(row.get("confidence"))
        labels = [str(label).strip().lower() for label in row.get("proposed_child_labels", []) or [] if str(label).strip()]
        allowed_ids = set(l2_by_id.get(source, {}).get("linked_obj_ids", []) or [])
        reps = _valid_representatives(row.get("representative_l1_ids", []), allowed_ids)
        if source in l2_by_id and confidence >= 0.5 and len(labels) >= 2 and reps:
            accepted["split_candidates"].append({**row, "proposed_child_labels": labels, "representative_l1_ids": reps})
        else:
            rejected.append({"proposal_type": "split_candidate", "proposal": row, "reason": "invalid_reference_or_low_confidence"})

    for row in parsed.get("assignment_concerns", []) or []:
        if not isinstance(row, dict):
            continue
        obj_id = str(row.get("obj_id", "") or "")
        l2_id = str(row.get("l2_id", "") or "")
        confidence = _safe_float(row.get("confidence"))
        if obj_id in obj_to_l2 and l2_id in l2_by_id and confidence >= 0.5:
            accepted["assignment_concerns"].append(row)
        else:
            rejected.append({"proposal_type": "assignment_concern", "proposal": row, "reason": "invalid_reference_or_low_confidence"})

    return {"accepted": accepted, "rejected": rejected}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def propose_induction_review(
    *,
    run_root: Path | str,
    profile: dict[str, Any],
    model: str = "",
    client: Any | None = None,
) -> dict[str, Any]:
    root = ensure_optimization_output(run_root)
    l2_path = root / "l2" / "l2_view.json"
    l2_view = load_json(l2_path)
    l2_nodes = list(l2_view.get("l2_nodes", []) or [])
    selected_model = model or os.getenv("GEMINI_MODEL", "").strip() or "gemini-2.5-pro"
    api_dir = root / "api_calls"
    api_dir.mkdir(parents=True, exist_ok=True)

    start = time.perf_counter()
    raw_text = ""
    parsed: dict[str, Any] = {}
    usage_metadata: dict[str, Any] = {}
    error = ""
    if client is None:
        from share_mem.l1.gemini_clients import create_gemini_client

        client = create_gemini_client()
    prompt = _build_prompt(l2_nodes, profile)
    try:
        response = client.models.generate_content(
            model=selected_model,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        raw_text = _response_text(response)
        usage_metadata = _usage_metadata(response)
        parsed = _extract_json(raw_text)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        parsed = {}
    latency_ms = round((time.perf_counter() - start) * 1000, 3)
    validation = _validate_proposals(parsed, l2_nodes)
    accepted = validation["accepted"]
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "status": "llm_induction_proposals_written" if not error else "llm_induction_proposals_failed",
        "model": selected_model,
        "latency_ms": latency_ms,
        "accepted_counts": {key: len(value) for key, value in accepted.items()},
        "rejected_count": len(validation["rejected"]),
        **accepted,
        "rejected": validation["rejected"],
        "usage_metadata": usage_metadata,
        "error": error,
    }
    write_json(root / "l2" / "llm_induction_proposals.json", report)
    write_json(
        api_dir / "0001_l2_induction_proposal.json",
        {
            "schema_version": 1,
            "created_at_utc": utc_now_iso(),
            "stage": "l2_induction_proposal",
            "model": selected_model,
            "prompt": prompt,
            "raw_response": raw_text,
            "parsed_json": parsed,
            "latency_ms": latency_ms,
            "usage_metadata": usage_metadata,
            "error": error,
        },
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Create sidecar-only LLM induction review proposals for an optimization v2 run.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--model", default="")
    args = parser.parse_args()
    report = propose_induction_review(
        run_root=args.run_root,
        profile=load_profile(args.profile),
        model=args.model,
    )
    print(
        "[optimization:v2] induction proposal complete: "
        f"status={report['status']} splits={report['accepted_counts']['split_candidates']} "
        f"merges={report['accepted_counts']['merge_candidates']}"
    )


if __name__ == "__main__":
    main()
