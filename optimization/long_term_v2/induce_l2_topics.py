from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from optimization.long_term_v2.io_utils import utc_now_iso, write_json, write_text
from optimization.long_term_v2.profiles import (
    profile_generic_topic_labels,
    profile_rejected_topic_labels,
    profile_role_artifact_tokens,
    profile_role_artifact_terms,
    profile_stopwords,
    profile_type_like_labels,
)
from optimization.long_term_v2.schemas import L2_SCHEMA_VERSION
from optimization.long_term_v2.text_utils import jaccard, normalize_phrase, slugify, tokens
from share_mem.store import iter_l1_objects


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_bad_label(label: str, *, profile: dict[str, Any]) -> bool:
    clean = normalize_phrase(label)
    parts = clean.split()
    generic_labels = profile_generic_topic_labels(profile)
    return (
        clean in profile_type_like_labels(profile)
        or clean in profile_rejected_topic_labels(profile)
        or clean in generic_labels
        or (len(parts) == 1 and parts[0] in generic_labels)
    )


def _generic_token_count(term: str, *, profile: dict[str, Any]) -> int:
    generic_labels = profile_generic_topic_labels(profile)
    return sum(1 for part in term.split() if part in generic_labels)


def _specific_token_count(term: str, *, profile: dict[str, Any]) -> int:
    return len(term.split()) - _generic_token_count(term, profile=profile)


def _all_terms(row: dict[str, Any], *, profile: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for value in row.get("candidate_terms", []) or []:
        clean = normalize_phrase(str(value))
        if clean and not _is_bad_label(clean, profile=profile):
            terms.append(clean)
    for values in (row.get("semantic_facets", {}) or {}).values():
        for value in values or []:
            clean = normalize_phrase(str(value))
            if clean and not _is_bad_label(clean, profile=profile):
                terms.append(clean)
    for topic in (row.get("source_signals", {}) or {}).get("related_topics", []) or []:
        clean = normalize_phrase(str(topic))
        if clean and not _is_bad_label(clean, profile=profile):
            terms.append(clean)
    deduped: list[str] = []
    for term in terms:
        if term not in deduped:
            deduped.append(term)
    return deduped


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _is_role_artifact(term: str, *, profile: dict[str, Any]) -> bool:
    parts = term.split()
    role_terms = profile_role_artifact_terms(profile)
    role_tokens = profile_role_artifact_tokens(profile)
    role_count = sum(1 for part in parts if part in role_tokens)
    return role_count >= 2 or term in role_terms


def _top_semantic_terms_for_l2(
    *,
    obj_ids: list[str],
    object_rows: dict[str, Any],
    profile: dict[str, Any],
    max_terms: int = 20,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for obj_id in obj_ids:
        row = object_rows.get(obj_id, {}) or {}
        for term in row.get("candidate_terms", []) or []:
            clean = normalize_phrase(str(term))
            if not clean or _is_bad_label(clean, profile=profile) or _is_role_artifact(clean, profile=profile):
                continue
            if str(profile.get("topic_key_language", "") or "").lower().startswith("en") and _has_cjk(clean):
                continue
            counts[clean] += 1
    terms = []
    for term, count in counts.most_common(max_terms):
        terms.append({"term": term, "object_count": count})
    return terms


def _choose_topic_label(
    row: dict[str, Any],
    *,
    profile: dict[str, Any],
    document_frequency: Counter[str],
    min_topic_evidence: int,
    total_object_count: int,
    max_l2_topic_share: float,
) -> str:
    terms = _all_terms(row, profile=profile)
    if not terms:
        return ""
    scored: list[tuple[float, str]] = []
    content_terms = {normalize_phrase(str(term)) for term in row.get("candidate_terms", []) or []}
    candidate_rank = {
        normalize_phrase(str(term)): index
        for index, term in enumerate(row.get("candidate_terms", []) or [])
        if str(term).strip()
    }
    facet_terms = {
        normalize_phrase(str(term))
        for values in (row.get("semantic_facets", {}) or {}).values()
        for term in (values or [])
    }
    related_terms = {
        normalize_phrase(str(term))
        for term in (row.get("source_signals", {}) or {}).get("related_topics", []) or []
    }
    for term in terms:
        df = document_frequency[term]
        token_count = len(term.split())
        generic_token_count = _generic_token_count(term, profile=profile)
        specific_token_count = token_count - generic_token_count
        if token_count == 1 and generic_token_count:
            continue
        if df < 2 and _safe_float(row.get("importance")) < 0.75:
            continue
        share = df / max(total_object_count, 1)
        capped_df = min(df, max(min_topic_evidence * 3, 1))
        phrase_bonus = 1.15 if token_count == 2 else 0.65 if token_count >= 3 else 0.0
        score = (capped_df * 1.4) + phrase_bonus
        score += min(specific_token_count, 3) * 0.2
        if df >= min_topic_evidence:
            score += 2.0
        if share > max_l2_topic_share:
            score -= (share - max_l2_topic_share) * 30.0
        if token_count == 1:
            score -= 3.0
        if token_count == 1 and generic_token_count:
            score -= generic_token_count * 0.35
        if term in content_terms or term in facet_terms:
            score += 1.0
            if token_count >= 2:
                score += max(0.0, 2.0 - 0.25 * candidate_rank.get(term, 8))
        elif term in related_terms:
            score += 0.25
        scored.append((score, term))
    if not scored:
        return ""
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][1]


def _summary_for_obj(obj: dict[str, Any]) -> str:
    content = str(obj.get("content", "") or "").strip()
    return content[:260]


def _topic_state(label: str, timeline: list[dict[str, Any]]) -> dict[str, Any]:
    if not timeline:
        return {
            "current_state": f"No linked L1 evidence currently supports {label}.",
            "evolution_summary": "",
            "representative_l1_ids": [],
        }
    earliest = timeline[0]
    latest = timeline[-1]
    reps = [row["obj_id"] for row in timeline[:3]]
    return {
        "current_state": (
            f"Current position: {latest['summary']}"
        ),
        "evolution_summary": (
            f"This topic began with {earliest['obj_id']}: {earliest['summary']} "
            f"Latest evidence is {latest['obj_id']}: {latest['summary']}"
        )[:700],
        "latest_position": latest["summary"],
        "open_tensions": [],
        "representative_l1_ids": reps,
    }


def _semantic_signature(terms: list[str], *, profile: dict[str, Any]) -> set[str]:
    stopword_set = (
        profile_stopwords(profile)
        | profile_generic_topic_labels(profile)
        | profile_rejected_topic_labels(profile)
        | profile_type_like_labels(profile)
        | profile_role_artifact_tokens(profile)
    )
    signature = set(tokens(" ".join(terms), stopwords=stopword_set))
    if str(profile.get("topic_key_language", "") or "").lower().startswith("en"):
        signature = {term for term in signature if not _has_cjk(term)}
    return signature


def _row_semantic_signature(row: dict[str, Any], *, profile: dict[str, Any]) -> set[str]:
    terms = _all_terms(row, profile=profile)
    source = row.get("source_signals", {}) or {}
    terms.extend([str(source.get("content", "") or ""), str(source.get("evidence", "") or "")])
    return _semantic_signature(terms, profile=profile)


def _rescue_semantically_related_unlinked(
    *,
    unlinked: list[dict[str, Any]],
    grouped: dict[str, list[str]],
    assignments: dict[str, Any],
    object_rows: dict[str, Any],
    objects_by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]],
    profile: dict[str, Any],
    min_importance: float,
    min_confidence: float,
) -> list[dict[str, Any]]:
    if not grouped:
        return unlinked
    topic_signatures: dict[str, set[str]] = {}
    for label, obj_ids in grouped.items():
        terms = [label]
        for obj_id in obj_ids:
            row = object_rows.get(obj_id, {}) or {}
            terms.extend(_all_terms(row, profile=profile))
            source = row.get("source_signals", {}) or {}
            terms.extend([str(source.get("content", "") or ""), str(source.get("evidence", "") or "")])
        topic_signatures[label] = _semantic_signature(terms, profile=profile)

    remaining: list[dict[str, Any]] = []
    for item in unlinked:
        obj_id = str(item.get("obj_id", "") or "")
        if not obj_id or obj_id in assignments:
            continue
        importance = _safe_float(item.get("importance"))
        if importance < min_importance:
            remaining.append(item)
            continue
        row = object_rows.get(obj_id, {}) or {}
        if item.get("candidate_label"):
            row = {**row, "candidate_terms": list(row.get("candidate_terms", []) or []) + [str(item.get("candidate_label"))]}
        row_signature = _row_semantic_signature(row, profile=profile)
        if len(row_signature) < 2:
            remaining.append(item)
            continue
        best_label = ""
        best_score = 0.0
        best_shared: set[str] = set()
        for label, signature in topic_signatures.items():
            shared = row_signature & signature
            if len(shared) < 2:
                continue
            containment = len(shared) / max(1, min(len(row_signature), len(signature)))
            score = 0.7 * containment + 0.3 * jaccard(row_signature, signature)
            if score > best_score:
                best_label = label
                best_score = score
                best_shared = shared
        if not best_label or best_score < 0.18:
            remaining.append(item)
            continue
        meeting, _obj = objects_by_id.get(obj_id, ({}, {}))
        grouped[best_label].append(obj_id)
        l2_id = f"L2-{slugify(best_label)}"
        confidence = min(0.82, 0.32 + best_score * 0.6 + importance * 0.12)
        if confidence < min_confidence:
            remaining.append(
                {
                    **item,
                    "reason": "semantic_rescue_low_confidence_review",
                    "candidate_label": best_label,
                    "semantic_similarity": round(best_score, 3),
                    "shared_terms": sorted(best_shared),
                    "rescue_confidence": round(confidence, 3),
                }
            )
            continue
        assignments[obj_id] = {
            "obj_id": obj_id,
            "l2_id": l2_id,
            "l2_label": best_label,
            "confidence": round(confidence, 3),
            "assignment_mode": "semantic_rescue",
            "score_breakdown": {
                "semantic_similarity": round(best_score, 3),
                "shared_terms": sorted(best_shared),
                "importance": round(importance, 3),
                "related_topics_used": bool((row.get("source_signals", {}) or {}).get("related_topics")),
            },
            "rationale": (
                f"Rescued from an otherwise non-durable singleton because its evidence shares "
                f"{len(best_shared)} semantic signal(s) with the existing durable topic '{best_label}'."
            ),
            "alternatives": [],
            "review": confidence < 0.55,
            "meeting_id": str(meeting.get("meeting_id", "") or ""),
        }
    return remaining


def induce_l2_topics(
    *,
    tree: dict[str, Any],
    semantic_key_index: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    object_rows = semantic_key_index.get("objects", {}) or {}
    term_docs: dict[str, set[str]] = defaultdict(set)
    for obj_id, row in object_rows.items():
        for term in _all_terms(row, profile=profile):
            term_docs[term].add(obj_id)
    document_frequency = Counter({term: len(ids) for term, ids in term_docs.items()})

    l2_policy = profile.get("l2_policy", {}) or {}
    min_topic_evidence = int(l2_policy.get("min_topic_evidence", 4) or 4)
    min_confidence = float(l2_policy.get("minimum_assignment_confidence", 0.25) or 0.25)
    high_importance = float(l2_policy.get("high_importance_threshold", 0.7) or 0.7)
    max_l2_topic_share = float(l2_policy.get("max_l2_topic_share_before_specificity_penalty", 0.18) or 0.18)

    objects_by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for meeting, obj in iter_l1_objects(tree):
        objects_by_id[str(obj.get("obj_id", "") or "")] = (meeting, obj)

    assignments: dict[str, Any] = {}
    grouped: dict[str, list[str]] = defaultdict(list)
    unlinked: list[dict[str, Any]] = []

    for obj_id, row in sorted(object_rows.items()):
        meeting, obj = objects_by_id.get(obj_id, ({}, {}))
        label = _choose_topic_label(
            row,
            profile=profile,
            document_frequency=document_frequency,
            min_topic_evidence=min_topic_evidence,
            total_object_count=len(object_rows),
            max_l2_topic_share=max_l2_topic_share,
        )
        if not label:
            unlinked.append(
                {
                    "obj_id": obj_id,
                    "reason": "no_repeated_or_high_confidence_semantic_key",
                    "importance": _safe_float(obj.get("importance")),
                }
            )
            continue
        df = document_frequency[label]
        importance = _safe_float(obj.get("importance"))
        confidence = min(0.95, 0.2 + (df / max(min_topic_evidence, 1)) * 0.35 + importance * 0.25)
        if df < min_topic_evidence and importance < high_importance:
            unlinked.append(
                {
                    "obj_id": obj_id,
                    "reason": "candidate_topic_not_durable_enough",
                    "candidate_label": label,
                    "importance": importance,
                }
            )
            continue
        if confidence < min_confidence:
            unlinked.append({"obj_id": obj_id, "reason": "low_assignment_confidence", "candidate_label": label})
            continue
        grouped[label].append(obj_id)
        l2_id = f"L2-{slugify(label)}"
        assignments[obj_id] = {
            "obj_id": obj_id,
            "l2_id": l2_id,
            "l2_label": label,
            "confidence": round(confidence, 3),
            "score_breakdown": {
                "semantic_key_frequency": round(df / max(len(object_rows), 1), 3),
                "importance": round(importance, 3),
                "related_topics_used": bool((row.get("source_signals", {}) or {}).get("related_topics")),
            },
            "rationale": (
                f"Assigned to '{label}' because the L1 evidence shares this recurring semantic key "
                f"with {df} object(s); related_topics are only treated as one optional source signal."
            ),
            "alternatives": [],
            "review": confidence < 0.45,
            "meeting_id": str(meeting.get("meeting_id", "") or ""),
        }

    allow_single_high = bool(l2_policy.get("allow_single_meeting_topic_if_high_importance", True))
    for label, obj_ids in list(grouped.items()):
        if len(obj_ids) != 1:
            continue
        obj_id = obj_ids[0]
        _meeting, obj = objects_by_id.get(obj_id, ({}, {}))
        importance = _safe_float(obj.get("importance"))
        if allow_single_high and importance >= high_importance:
            continue
        grouped.pop(label, None)
        assignments.pop(obj_id, None)
        unlinked.append(
            {
                "obj_id": obj_id,
                "reason": "singleton_l2_not_durable_enough",
                "candidate_label": label,
                "importance": importance,
            }
        )

    semantic_rescue_min_importance = float(l2_policy.get("semantic_rescue_min_importance", 0.55) or 0.55)
    semantic_rescue_min_confidence = float(l2_policy.get("semantic_rescue_min_confidence", 0.6) or 0.6)
    unlinked = _rescue_semantically_related_unlinked(
        unlinked=unlinked,
        grouped=grouped,
        assignments=assignments,
        object_rows=object_rows,
        objects_by_id=objects_by_id,
        profile=profile,
        min_importance=semantic_rescue_min_importance,
        min_confidence=semantic_rescue_min_confidence,
    )

    l2_nodes: list[dict[str, Any]] = []
    for label, obj_ids in sorted(grouped.items()):
        timeline: list[dict[str, Any]] = []
        meeting_ids: set[str] = set()
        for obj_id in sorted(obj_ids):
            meeting, obj = objects_by_id[obj_id]
            meeting_id = str(meeting.get("meeting_id", "") or "")
            meeting_ids.add(meeting_id)
            timeline.append(
                {
                    "meeting_id": meeting_id,
                    "meeting_date": str(meeting.get("meeting_date", "") or ""),
                    "obj_id": obj_id,
                    "summary": _summary_for_obj(obj),
                    "importance": _safe_float(obj.get("importance")),
                }
            )
        timeline.sort(key=lambda row: (row["meeting_date"], row["meeting_id"], row["obj_id"]))
        state = _topic_state(label, timeline)
        top_semantic_terms = _top_semantic_terms_for_l2(
            obj_ids=sorted(obj_ids),
            object_rows=object_rows,
            profile=profile,
        )
        l2_nodes.append(
            {
                "l2_id": f"L2-{slugify(label)}",
                "label": label,
                "definition": f"Evidence-backed mentor-mentee topic about {label}.",
                "inclusion_criteria": [f"L1 evidence discusses {label} or a close semantic equivalent."],
                "exclusion_criteria": ["Purely administrative or one-off low-importance mentions."],
                "linked_obj_ids": sorted(obj_ids),
                "meeting_ids": sorted(meeting_ids),
                "timeline_digest": timeline,
                "confidence": round(min(0.95, 0.45 + len(obj_ids) / max(len(object_rows), 1)), 3),
                "creation_rationale": (
                    f"Created from recurring semantic evidence, not from a hardcoded Grace topic map. "
                    f"{len(obj_ids)} L1 object(s) support this label."
                ),
                "top_semantic_terms": top_semantic_terms,
                **state,
            }
        )

    return {
        "schema_version": L2_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "source": "optimization_long_term_v2_induction",
        "profile_name": profile.get("name", ""),
        "l2_nodes": sorted(l2_nodes, key=lambda node: (-len(node["linked_obj_ids"]), node["label"])),
        "l2_index": dict(sorted(assignments.items())),
        "unlinked_objects": unlinked,
        "manual_review_items": [
            row for row in unlinked if row.get("importance", 0) >= high_importance
        ],
        "diagnostics": {
            "candidate_term_count": len(document_frequency),
            "related_topics_direct_assignment": False,
            "min_topic_evidence": min_topic_evidence,
        },
    }


def write_l2_outputs(*, out_dir: Path, l2_result: dict[str, Any]) -> None:
    l2_dir = out_dir / "l2"
    write_json(l2_dir / "l2_view.json", {k: v for k, v in l2_result.items() if k != "l2_index"})
    write_json(l2_dir / "l2_index.json", l2_result["l2_index"])
    write_json(l2_dir / "unlinked_l1_report.json", {"unlinked_objects": l2_result["unlinked_objects"]})
    write_json(l2_dir / "l2_assignment_rationale.json", l2_result["l2_index"])
    write_text(
        l2_dir / "l2_summary.md",
        "\n".join(
            [
                "# Optimization L2 Summary",
                "",
                f"- topics: {len(l2_result['l2_nodes'])}",
                f"- linked L1: {len(l2_result['l2_index'])}",
                f"- unlinked L1: {len(l2_result['unlinked_objects'])}",
                "",
            ]
        ),
    )


def topic_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    text_a = " ".join([a.get("label", ""), a.get("definition", ""), a.get("current_state", "")])
    text_b = " ".join([b.get("label", ""), b.get("definition", ""), b.get("current_state", "")])
    return jaccard(tokens(text_a), tokens(text_b))
