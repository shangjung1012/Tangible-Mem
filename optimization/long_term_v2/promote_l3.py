from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from optimization.long_term_v2.io_utils import utc_now_iso, write_json, write_text
from optimization.long_term_v2.profiles import (
    profile_generic_ngram_terms,
    profile_max_cjk_token_chars,
    profile_child_label_normalization,
    profile_role_artifact_tokens,
    profile_role_artifact_terms,
    profile_stopwords,
    profile_weak_child_terms,
)
from optimization.long_term_v2.schemas import L3_SCHEMA_VERSION
from optimization.long_term_v2.text_utils import ngrams, slugify, tokens, token_sequences


def _percentile(values: list[int], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _promotion_threshold(l2_nodes: list[dict[str, Any]], profile: dict[str, Any]) -> int:
    sizes = [len(node.get("linked_obj_ids", []) or []) for node in l2_nodes]
    l3_policy = profile.get("l3_policy", {}) or {}
    minimum = int(l3_policy.get("min_absolute_threshold", 10) or 10)
    child_range = l3_policy.get("target_child_l2_size_range", [6, 28]) or [6, 28]
    target_child_max = int(child_range[1]) if len(child_range) > 1 else 28
    if not sizes:
        return minimum
    p85 = int(round(_percentile(sizes, 0.85)))
    total_l1 = sum(sizes)
    if total_l1 <= 50:
        return max(minimum, p85)
    return max(minimum, target_child_max, p85)


def _target_child_count(node: dict[str, Any], profile: dict[str, Any]) -> int:
    l3_policy = profile.get("l3_policy", {}) or {}
    child_range = l3_policy.get("target_child_l2_size_range", [6, 28]) or [6, 28]
    target_child_max = int(child_range[1]) if len(child_range) > 1 else 28
    min_child_count = int(l3_policy.get("min_child_l2_count", 2) or 2)
    max_child_count = int(l3_policy.get("max_child_l2_count", 12) or 12)
    event_count = len(node.get("linked_obj_ids", []) or [])
    if target_child_max <= 0:
        return min_child_count
    adaptive_count = (event_count + target_child_max - 1) // target_child_max
    return max(min_child_count, min(max_child_count, adaptive_count))


def _max_materialized_child_size(profile: dict[str, Any]) -> int:
    l3_policy = profile.get("l3_policy", {}) or {}
    return int(l3_policy.get("max_materialized_child_l2_size", 35) or 35)


def _split_needs_review_only(children: list[dict[str, Any]], *, source_event_count: int, profile: dict[str, Any]) -> dict[str, Any]:
    if not children:
        return {"needs_review": True, "reason_codes": ["no_child_candidates"], "max_child_event_count": 0}
    counts = [len(child.get("linked_obj_ids", []) or []) for child in children]
    max_count = max(counts) if counts else 0
    non_empty_count = sum(1 for count in counts if count > 0)
    max_allowed = _max_materialized_child_size(profile)
    reason_codes: list[str] = []
    if non_empty_count < 2 and max_count > max_allowed:
        reason_codes.append("insufficient_non_empty_children")
    if max_count > max_allowed:
        reason_codes.append("dominant_oversized_child")
    if counts and counts.count(0) > len(counts) // 2 and max_count > max_allowed:
        reason_codes.append("too_many_empty_children")
    return {
        "needs_review": bool(reason_codes),
        "reason_codes": reason_codes,
        "max_child_event_count": max_count,
        "non_empty_child_count": non_empty_count,
    }


def _child_candidates_for_node(node: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    token_kwargs = {
        "stopwords": profile_stopwords(profile),
        "max_cjk_token_chars": profile_max_cjk_token_chars(profile),
    }
    parent_tokens = set(tokens(str(node.get("label", "") or ""), **token_kwargs))
    weak_single_terms = profile_weak_child_terms(profile)
    counts: Counter[str] = Counter()
    for row in node.get("top_semantic_terms", []) or []:
        term = _normalize_child_term(str(row.get("term", "") or ""), profile=profile)
        if _is_usable_child_term(term, profile=profile, weak_single_terms=weak_single_terms, parent_tokens=parent_tokens):
            counts[term] += int(row.get("object_count", 1) or 1) * 10
    for event in node.get("timeline_digest", []) or []:
        summary = str(event.get("summary", "") or "")
        terms = []
        for token_list in token_sequences(summary, **token_kwargs):
            terms.extend(
                _normalize_child_term(gram, profile=profile)
                for gram in ngrams(
                    token_list,
                    min_n=2,
                    max_n=3,
                    generic_terms=profile_generic_ngram_terms(profile),
                )
            )
        terms = [
            term
            for term in terms
            if _is_usable_child_term(term, profile=profile, weak_single_terms=weak_single_terms, parent_tokens=parent_tokens)
        ]
        counts.update(terms)

    child_count = _target_child_count(node, profile)
    candidates: list[dict[str, Any]] = []
    ranked_terms = sorted(
        counts.items(),
        key=lambda item: (-(item[1] + len(item[0].split()) * 4), -len(item[0].split()), item[0]),
    )
    for term, _ in ranked_terms[: child_count * 6]:
        if not term or term == node.get("label"):
            continue
        if any(term in candidate["label"] or candidate["label"] in term for candidate in candidates):
            continue
        candidates.append(
            {
                "child_l2_id": f"L2-{slugify(node.get('label', 'topic'))}-{slugify(term)}",
                "label": term,
                "assignment_criteria": [term],
                "split_reason": "Recurring subtopic term inside an oversized evidence-backed L2.",
            }
        )
        if len(candidates) >= child_count:
            break

    if len(candidates) < child_count:
        for idx in range(child_count - len(candidates)):
            label = f"{node.get('label', 'topic')} timeline slice {idx + 1}"
            candidates.append(
                {
                    "child_l2_id": f"L2-{slugify(label)}",
                    "label": label,
                    "assignment_criteria": [],
                    "split_reason": "Low-separability chronological slice used for reviewable prompt-budget control.",
                    "manual_review_required": True,
                }
            )
    return candidates


def _normalize_child_term(term: str, *, profile: dict[str, Any]) -> str:
    term = " ".join((term or "").strip().lower().split())
    normalization = profile_child_label_normalization(profile)
    surrounded = f" {term} "
    if any(str(blocker).lower() in surrounded for blocker in normalization.get("phrase_blockers", []) or []):
        return ""
    parts = term.split()
    part_set = set(parts)
    for alias in normalization.get("aliases", []) or []:
        if not isinstance(alias, dict):
            continue
        label = str(alias.get("label", "") or "").strip().lower()
        required = {str(value).strip().lower() for value in alias.get("required_terms", []) or [] if str(value).strip()}
        subset = {str(value).strip().lower() for value in alias.get("subset_terms", []) or [] if str(value).strip()}
        prefix = [str(value).strip().lower() for value in alias.get("prefix_terms", []) or [] if str(value).strip()]
        if required and not required.issubset(part_set):
            continue
        if subset and not part_set.issubset(subset):
            continue
        if prefix and parts[: len(prefix)] != prefix:
            continue
        if label:
            return label
    repeated_allow = {str(value).strip().lower() for value in normalization.get("allow_repeated_exact", []) or []}
    if len(set(parts)) < len(parts) and term not in repeated_allow:
        return ""
    for rejected in normalization.get("reject_if_contains_all", []) or []:
        rejected_set = {str(value).strip().lower() for value in rejected or [] if str(value).strip()}
        if rejected_set and rejected_set.issubset(part_set):
            return ""
    if len(parts) >= 3:
        last = parts[-1]
        if re_full_cjk(last) and len(last) >= 6:
            return " ".join(parts[:2])
    if any(term.startswith(str(prefix).strip().lower()) for prefix in normalization.get("reject_prefixes", []) or []):
        return ""
    if term in {str(value).strip().lower() for value in normalization.get("reject_exact", []) or []}:
        return ""
    return term


def re_full_cjk(text: str) -> bool:
    return bool(text) and all("\u4e00" <= char <= "\u9fff" for char in text)


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _is_role_artifact(term: str, *, profile: dict[str, Any]) -> bool:
    parts = term.split()
    role_terms = profile_role_artifact_terms(profile)
    role_tokens = profile_role_artifact_tokens(profile)
    role_count = sum(1 for part in parts if part in role_tokens)
    return role_count >= 2 or term in role_terms


def _is_usable_child_term(
    term: str,
    *,
    profile: dict[str, Any],
    weak_single_terms: set[str],
    parent_tokens: set[str],
) -> bool:
    if not term or len(term) > 48:
        return False
    parts = term.split()
    if len(parts) < 2:
        return False
    term_tokens = set(parts)
    if parent_tokens.issuperset(term_tokens):
        return False
    normalization = profile_child_label_normalization(profile)
    alias_labels = {
        str(alias.get("label", "") or "").strip().lower()
        for alias in normalization.get("aliases", []) or []
        if isinstance(alias, dict) and str(alias.get("label", "") or "").strip()
    }
    if term_tokens.issubset(weak_single_terms) and term not in alias_labels:
        return False
    if _is_role_artifact(term, profile=profile):
        return False
    if str(profile.get("topic_key_language", "") or "").lower().startswith("en") and _has_cjk(term):
        return False
    if term.startswith("term ") or term.endswith(" term"):
        return False
    return True


def _assign_events_to_children(node: dict[str, Any], candidates: list[dict[str, Any]], *, profile: dict[str, Any]) -> list[dict[str, Any]]:
    assignments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    token_kwargs = {
        "stopwords": profile_stopwords(profile),
        "max_cjk_token_chars": profile_max_cjk_token_chars(profile),
    }
    for index, event in enumerate(node.get("timeline_digest", []) or []):
        summary_tokens = set(tokens(str(event.get("summary", "") or ""), **token_kwargs))
        best_child = ""
        best_score = -1
        for candidate in candidates:
            criteria_tokens = set(tokens(" ".join(candidate.get("assignment_criteria", []) or []), **token_kwargs))
            score = len(summary_tokens & criteria_tokens)
            if score > best_score:
                best_score = score
                best_child = candidate["child_l2_id"]
        if best_score <= 0:
            best_child = candidates[index % len(candidates)]["child_l2_id"]
        assignments[best_child].append(event)

    children: list[dict[str, Any]] = []
    for candidate in candidates:
        events = assignments.get(candidate["child_l2_id"], [])
        obj_ids = [str(event.get("obj_id", "") or "") for event in events]
        latest = events[-1]["summary"] if events else ""
        children.append(
            {
                **candidate,
                "linked_obj_ids": obj_ids,
                "event_count": len(events),
                "timeline_digest": events,
                "current_state": (
                    f"Child topic '{candidate['label']}' has {len(events)} assigned L1 evidence object(s). "
                    f"Latest evidence: {latest[:220]}"
                ),
                "confidence": 0.55 if candidate.get("manual_review_required") else 0.72,
            }
        )
    return children


def build_l3_view(*, l2_result: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    l2_nodes = list(l2_result.get("l2_nodes", []) or [])
    threshold = _promotion_threshold(l2_nodes, profile)
    parents: list[dict[str, Any]] = []
    l3_index: dict[str, Any] = {}
    merge_reviews: list[dict[str, Any]] = []
    for node in l2_nodes:
        event_count = len(node.get("linked_obj_ids", []) or [])
        if event_count < threshold:
            continue
        candidates = _child_candidates_for_node(node, profile)
        children = _assign_events_to_children(node, candidates, profile=profile)
        split_quality = _split_needs_review_only(children, source_event_count=event_count, profile=profile)
        if split_quality["needs_review"]:
            merge_reviews.append(
                {
                    "parent_l3_id": "",
                    "source_l2_id": node.get("l2_id", ""),
                    "source_l2_label": node.get("label", ""),
                    "source_event_count": event_count,
                    "recommended_target_child_l2_id": "",
                    "recommended_target_label": "",
                    "similarity_score": 0.0,
                    "reason_codes": split_quality["reason_codes"],
                    "action": "needs_split_review",
                    "max_child_event_count": split_quality["max_child_event_count"],
                    "non_empty_child_count": split_quality["non_empty_child_count"],
                }
            )
            continue
        l3_id = f"L3-{slugify(node.get('label', 'topic'))}"
        parent = {
            "l3_id": l3_id,
            "label": str(node.get("label", "") or ""),
            "source_l2_id": node.get("l2_id", ""),
            "promotion_reason": {
                "event_count": event_count,
                "adaptive_threshold": threshold,
                "reason_codes": ["oversized_relative_to_profile"],
            },
            "child_l2_nodes": children,
            "confidence": round(min(0.9, 0.5 + event_count / max(sum(len(n.get("linked_obj_ids", []) or []) for n in l2_nodes), 1)), 3),
        }
        parents.append(parent)
        for child in children:
            if child["event_count"] < 3:
                merge_reviews.append(
                    {
                        "parent_l3_id": l3_id,
                        "source_child_l2_id": child["child_l2_id"],
                        "source_child_l2_label": child["label"],
                        "source_event_count": child["event_count"],
                        "action": "needs_merge_review",
                        "reason_codes": ["too_few_l1_nodes"],
                    }
                )
            for obj_id in child["linked_obj_ids"]:
                l3_index[obj_id] = {
                    "parent_l3_id": l3_id,
                    "parent_l3_label": parent["label"],
                    "child_l2_id": child["child_l2_id"],
                    "child_l2_label": child["label"],
                }
    return {
        "schema_version": L3_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "source": "optimization_long_term_v2_adaptive_promotion",
        "adaptive_threshold": threshold,
        "l3_parents": parents,
        "l3_index": dict(sorted(l3_index.items())),
        "l2_merge_review": {
            "schema_version": 1,
            "generated_at_utc": utc_now_iso(),
            "merge_reviews": merge_reviews,
        },
    }


def write_l3_outputs(*, out_dir: Path, l3_result: dict[str, Any]) -> None:
    l3_dir = out_dir / "l3"
    write_json(
        l3_dir / "l3_view.json",
        {key: value for key, value in l3_result.items() if key not in {"l3_index", "l2_merge_review"}},
    )
    write_json(l3_dir / "l3_index.json", l3_result["l3_index"])
    write_json(l3_dir / "l2_merge_review.json", l3_result["l2_merge_review"])
    write_text(
        l3_dir / "l3_summary.md",
        "\n".join(
            [
                "# Optimization L3 Summary",
                "",
                f"- adaptive threshold: {l3_result['adaptive_threshold']}",
                f"- L3 parents: {len(l3_result['l3_parents'])}",
                f"- assigned L1 through L3: {len(l3_result['l3_index'])}",
                "",
            ]
        ),
    )
