from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from optimization.long_term_v2.induce_l2_topics import _is_bad_label
from optimization.long_term_v2.io_utils import ensure_optimization_output, utc_now_iso, write_json
from optimization.long_term_v2.text_utils import normalize_phrase


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
    for name in (
        "prompt_token_count",
        "candidates_token_count",
        "total_token_count",
        "thoughts_token_count",
    ):
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
        if array_start >= 0 and array_end > array_start and (
            object_start < 0 or array_start < object_start
        ):
            parsed = json.loads(text[array_start : array_end + 1])
        elif object_start >= 0 and object_end > object_start:
            parsed = json.loads(text[object_start : object_end + 1])
        else:
            raise
    if isinstance(parsed, list):
        return {"topics": parsed}
    if not isinstance(parsed, dict):
        raise ValueError("LLM topic refinement response must be a JSON object or array.")
    return parsed


def _compact_node_payload(node: dict[str, Any]) -> dict[str, Any]:
    timeline = []
    for event in (node.get("timeline_digest", []) or [])[:4]:
        timeline.append(
            {
                "obj_id": event.get("obj_id", ""),
                "meeting_id": event.get("meeting_id", ""),
                "summary": str(event.get("summary", "") or "")[:220],
            }
        )
    return {
        "l2_id": node.get("l2_id", ""),
        "current_label": node.get("label", ""),
        "event_count": len(node.get("linked_obj_ids", []) or []),
        "top_semantic_terms": node.get("top_semantic_terms", [])[:10],
        "representative_timeline": timeline,
    }


def _build_prompt(nodes: list[dict[str, Any]], profile: dict[str, Any]) -> str:
    compact_nodes = [_compact_node_payload(node) for node in nodes]
    payload = {
        "task": "Refine evidence-derived L2 topic labels for a mentor-mentee research meeting memory system.",
        "constraints": [
            "Use only the provided L1 evidence summaries and semantic terms.",
            "Do not invent project-specific labels that are not supported by evidence.",
            "Prefer concise English noun phrases, usually 2 to 5 words.",
            "Prefer stable noun labels such as 'dataset evaluation' or 'manager agent orchestration' over verb phrases such as 'applying X' or 'sourcing and evaluating Y'.",
            "Avoid labels that are merely L1 object types, generic buckets, or implementation artifacts.",
            "Keep a topic broad enough to cover its linked evidence but specific enough to be useful for retrieval.",
        ],
        "profile": {
            "domain": profile.get("domain", ""),
            "topic_key_language": profile.get("topic_key_language", ""),
            "semantic_facets": [facet.get("name", "") for facet in profile.get("semantic_facets", []) if isinstance(facet, dict)],
        },
        "topics": compact_nodes,
        "response_schema": {
            "topics": [
                {
                    "l2_id": "same id from input",
                    "recommended_label": "short evidence-backed topic label",
                    "definition": "one sentence topic definition",
                    "inclusion_criteria": ["what belongs here"],
                    "exclusion_criteria": ["what does not belong here"],
                    "confidence": 0.0,
                    "rationale": "why this label fits the evidence",
                }
            ]
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _is_safe_recommended_label(label: str, *, profile: dict[str, Any]) -> bool:
    clean = normalize_phrase(label)
    if not clean or _is_bad_label(clean, profile=profile):
        return False
    if len(clean) > 70:
        return False
    parts = clean.split()
    if len(parts) < 2:
        return False
    if str(profile.get("topic_key_language", "") or "").lower().startswith("en"):
        if any("\u4e00" <= char <= "\u9fff" for char in clean):
            return False
    return True


def _apply_refinements(
    l2_result: dict[str, Any],
    parsed: dict[str, Any],
    *,
    profile: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    refined = deepcopy(l2_result)
    proposals = parsed.get("topics", []) or []
    proposal_by_id = {
        str(row.get("l2_id", "") or ""): row
        for row in proposals
        if isinstance(row, dict) and str(row.get("l2_id", "") or "")
    }
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    labels_by_id: dict[str, str] = {}
    for node in refined.get("l2_nodes", []) or []:
        l2_id = str(node.get("l2_id", "") or "")
        proposal = proposal_by_id.get(l2_id)
        if not proposal:
            continue
        label = normalize_phrase(str(proposal.get("recommended_label", "") or ""))
        confidence = _safe_float(proposal.get("confidence"))
        if confidence < 0.5 or not _is_safe_recommended_label(label, profile=profile):
            rejected.append(
                {
                    "l2_id": l2_id,
                    "current_label": node.get("label", ""),
                    "recommended_label": label,
                    "confidence": confidence,
                    "reason": "unsafe_or_low_confidence_label",
                }
            )
            continue
        original = str(node.get("label", "") or "")
        node["original_label"] = original
        node["label"] = label
        node["label_source"] = "llm_refinement"
        node["llm_label_confidence"] = round(confidence, 3)
        if proposal.get("definition"):
            node["definition"] = str(proposal.get("definition", "") or "")
        if isinstance(proposal.get("inclusion_criteria"), list):
            node["inclusion_criteria"] = [str(value) for value in proposal["inclusion_criteria"] if str(value).strip()]
        if isinstance(proposal.get("exclusion_criteria"), list):
            node["exclusion_criteria"] = [str(value) for value in proposal["exclusion_criteria"] if str(value).strip()]
        if proposal.get("rationale"):
            node["llm_label_rationale"] = str(proposal.get("rationale", "") or "")
        labels_by_id[l2_id] = label
        applied.append(
            {
                "l2_id": l2_id,
                "original_label": original,
                "recommended_label": label,
                "confidence": round(confidence, 3),
            }
        )
    for assignment in (refined.get("l2_index", {}) or {}).values():
        if not isinstance(assignment, dict):
            continue
        l2_id = str(assignment.get("l2_id", "") or "")
        if l2_id in labels_by_id:
            assignment["original_l2_label"] = assignment.get("l2_label", "")
            assignment["l2_label"] = labels_by_id[l2_id]
            assignment["label_source"] = "llm_refinement"
    return refined, {"applied": applied, "rejected": rejected}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def refine_l2_result_with_llm(
    *,
    l2_result: dict[str, Any],
    profile: dict[str, Any],
    run_root: Path | str,
    model: str = "",
    client: Any | None = None,
    batch_size: int = 12,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = ensure_optimization_output(run_root)
    api_dir = root / "api_calls"
    l2_dir = root / "l2"
    api_dir.mkdir(parents=True, exist_ok=True)
    l2_dir.mkdir(parents=True, exist_ok=True)
    selected_model = model or os.getenv("GEMINI_MODEL", "").strip() or "gemini-2.5-pro"
    all_nodes = list(l2_result.get("l2_nodes", []) or [])
    node_batches = [
        all_nodes[index : index + max(1, batch_size)]
        for index in range(0, len(all_nodes), max(1, batch_size))
    ] or [[]]
    start = time.perf_counter()
    errors: list[str] = []
    usage_records: list[dict[str, Any]] = []
    parsed_topics: list[dict[str, Any]] = []
    try:
        if client is None:
            from share_mem.l1.gemini_clients import create_gemini_client

            client = create_gemini_client()
        for batch_index, batch in enumerate(node_batches, start=1):
            prompt = _build_prompt(batch, profile)
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
                usage_records.append(usage_metadata)
                parsed = _extract_json(raw_text)
                parsed_topics.extend(
                    row for row in parsed.get("topics", []) or [] if isinstance(row, dict)
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                errors.append(f"batch {batch_index}: {error}")
            batch_latency_ms = round((time.perf_counter() - batch_start) * 1000, 3)
            log_payload = {
                "schema_version": 1,
                "created_at_utc": utc_now_iso(),
                "stage": "l2_label_refinement",
                "batch_index": batch_index,
                "batch_count": len(node_batches),
                "model": selected_model,
                "prompt": prompt,
                "raw_response": raw_text,
                "parsed_json": parsed,
                "latency_ms": batch_latency_ms,
                "usage_metadata": usage_metadata,
                "error": error,
            }
            write_json(api_dir / f"{batch_index:04d}_l2_label_refinement.json", log_payload)
        parsed = {"topics": parsed_topics}
        refined, proposal_summary = _apply_refinements(l2_result, parsed, profile=profile)
        status = "llm_refinement_applied" if proposal_summary["applied"] else "llm_refinement_no_safe_labels"
    except Exception as exc:
        refined = deepcopy(l2_result)
        proposal_summary = {"applied": [], "rejected": []}
        errors.append(f"{type(exc).__name__}: {exc}")
        status = "llm_refinement_failed_fallback"
    latency_ms = round((time.perf_counter() - start) * 1000, 3)
    refinement_report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "status": status,
        "model": selected_model,
        "latency_ms": latency_ms,
        "applied_count": len(proposal_summary["applied"]),
        "rejected_count": len(proposal_summary["rejected"]),
        **proposal_summary,
        "errors": errors,
    }
    write_json(l2_dir / "llm_label_refinement.json", refinement_report)
    return refined, {
        "requested": True,
        "used": status == "llm_refinement_applied",
        "status": status,
        "model": selected_model,
        "latency_ms": latency_ms,
        "applied_count": refinement_report["applied_count"],
        "rejected_count": refinement_report["rejected_count"],
        "usage_metadata": usage_records,
        "errors": errors,
    }
