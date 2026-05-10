"""Sidecar data model helpers for promoting overcrowded L2 topics to L3."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import re
from typing import Any, Callable

L3_PROMOTION_SCHEMA_VERSION = 1
L3_ASSIGNMENT_CONFIDENCE_THRESHOLD = 0.55

ChildTaxonomyProposer = Callable[[dict[str, Any]], dict[str, Any]]
ChildAssignmentProposer = Callable[[dict[str, Any], list[dict[str, Any]]], list[dict[str, Any]]]

CHILD_TAXONOMY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "promoted_l3": {
            "type": "object",
            "properties": {
                "l3_id": {"type": "string"},
                "label": {"type": "string"},
            },
            "required": ["l3_id", "label"],
        },
        "child_l2_candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "child_l2_id": {"type": "string"},
                    "label": {"type": "string"},
                    "split_reason": {"type": "string"},
                    "assignment_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "child_l2_id",
                    "label",
                    "split_reason",
                    "assignment_criteria",
                ],
            },
        },
    },
    "required": ["promoted_l3", "child_l2_candidates"],
}

CHILD_ASSIGNMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "obj_id": {"type": "string"},
                    "child_l2_id": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["obj_id", "child_l2_id", "confidence", "reason"],
            },
        }
    },
    "required": ["assignments"],
}

DEFAULT_L3_PROMOTION_THRESHOLDS: dict[str, float] = {
    "absolute_l1_threshold": 24,
    "share_threshold": 0.30,
    "share_minimum_l1_count": 12,
    "min_child_l2_count": 2,
}

CHILD_L2_SIZE_BUCKETS = {
    "needs_merge_review": (0, 2),
    "weak_child_l2": (3, 4),
    "ideal": (5, 25),
    "acceptable_but_watch": (26, 35),
    "needs_split_review": (36, None),
}

DEFAULT_CHILD_L2_CANDIDATES_BY_SOURCE_L2_ID: dict[str, list[dict[str, Any]]] = {
    "L2-transcript-segmentation-and-idea-unit-coverage": [
        {
            "child_l2_id": "L2-fixed-vs-dynamic-chunking",
            "label": "fixed vs dynamic chunking",
            "split_reason": "Separate fixed-size chunking, dynamic chunking, adaptive segmentation, and top-down/bottom-up chunk strategy decisions.",
            "assignment_criteria": [
                "fixed chunk",
                "fixed-size",
                "fixed size",
                "dynamic chunk",
                "dynamic chunking",
                "adaptive segmentation",
                "adaptive window",
                "top-down",
                "bottom-up",
                "per-turn",
                "chunk size",
            ],
        },
        {
            "child_l2_id": "L2-window-and-boundary-selection",
            "label": "window and boundary selection",
            "split_reason": "Separate processing-window size, boundary selection, topic block length, overlap, and line-range control.",
            "assignment_criteria": [
                "window",
                "80-line",
                "80 line",
                "40 lines",
                "20 lines",
                "topic block",
                "boundary",
                "overlap",
                "line immediately following",
                "resume",
            ],
        },
        {
            "child_l2_id": "L2-tool-calling-transcript-reading",
            "label": "tool-calling transcript reading",
            "split_reason": "Separate programmer-controlled transcript reading, tool-callable segmentation functions, and read_segment workflow design.",
            "assignment_criteria": [
                "tool calling",
                "tool-callable",
                "function",
                "read_segment",
                "read segment",
                "programmer-controlled",
                "code-driven",
                "Gemini reads transcript lines",
            ],
        },
        {
            "child_l2_id": "L2-idea-unit-generation",
            "label": "idea-unit generation",
            "split_reason": "Separate creation and definition of idea units as atomic transcript-processing units.",
            "assignment_criteria": [
                "idea unit",
                "idea-unit",
                "idea units",
                "atomic unit",
                "single utterance",
                "granular viewpoint",
            ],
        },
        {
            "child_l2_id": "L2-idea-unit-granularity-and-semantics",
            "label": "idea-unit granularity and semantics",
            "split_reason": "Separate what counts as an idea unit, how granular it should be, and whether low-semantic utterances should become units.",
            "assignment_criteria": [
                "idea unit definition",
                "granularity",
                "granular",
                "semantic unit",
                "segment and idea unit",
                "segment 與 idea unit",
                "區別",
                "細粒度",
                "微小",
                "微主題",
                "無語義",
                "嗯哼",
                "話語",
            ],
        },
        {
            "child_l2_id": "L2-idea-unit-generation-methods",
            "label": "idea-unit generation methods",
            "split_reason": "Separate recipe-based, prompt-based, iterative, and pre-segmentation methods for generating idea units.",
            "assignment_criteria": [
                "recipe",
                "prompt engineering",
                "generation method",
                "pre-segmentation",
                "iterative method",
                "iterative generation",
                "配方",
                "提示工程",
                "迭代",
                "預分割",
                "生成方法",
                "來回",
                "非線性",
            ],
        },
        {
            "child_l2_id": "L2-idea-unit-candidate-classification",
            "label": "idea-unit candidate classification",
            "split_reason": "Separate type-agent labeling, candidate generation, reconciliation, and classification of idea units.",
            "assignment_criteria": [
                "candidate",
                "candidates",
                "type agent",
                "type agents",
                "classification",
                "label",
                "labels",
                "reconcile",
                "reconciliation",
                "agent 標記",
                "標記",
                "標籤",
                "六種",
                "並行",
                "協調",
                "分類",
            ],
        },
        {
            "child_l2_id": "L2-missing-line-coverage",
            "label": "missing-line coverage",
            "split_reason": "Separate transcript coverage validation, missed-line detection, and gap filling.",
            "assignment_criteria": [
                "missed line",
                "missed lines",
                "gap",
                "gaps",
                "coverage",
                "100%",
                "verification",
                "check every",
            ],
        },
        {
            "child_l2_id": "L2-repair-and-coarsening",
            "label": "repair and coarsening",
            "split_reason": "Separate repair, coarsening, merging, and quality control of overly small or low-quality units.",
            "assignment_criteria": [
                "repair",
                "coarsening",
                "merge",
                "merging",
                "low-quality",
                "low quality",
                "batch",
                "combining",
            ],
        },
        {
            "child_l2_id": "L2-cross-window-continuity",
            "label": "cross-window continuity",
            "split_reason": "Separate continuity across processing windows, incomplete trailing segments, non-adjacent related ideas, and interwoven topics.",
            "assignment_criteria": [
                "incomplete",
                "span",
                "spans",
                "previous chunk",
                "non-adjacent",
                "interwoven",
                "continuity",
                "truncated",
            ],
        },
        {
            "child_l2_id": "L2-evidence-grounding-and-line-coverage",
            "label": "evidence grounding and line coverage",
            "split_reason": "Separate evidence anchoring, line ranges, and support verification.",
            "assignment_criteria": [
                "evidence",
                "grounding",
                "line range",
                "line ranges",
                "source data",
                "source",
                "timestamp",
                "audio",
                "range",
                "support",
            ],
        },
    ],
    "L2-memory-evaluation-strategy": [
        {
            "child_l2_id": "L2-overall-memory-system-evaluation",
            "label": "Overall Memory System Evaluation",
            "split_reason": "Separate overall evaluation design, ablation setup, and benchmark comparison strategy.",
            "assignment_criteria": [
                "evaluation plan",
                "ablation",
                "baseline",
                "system evaluation",
                "rag-only",
                "short-term-only",
                "long-term-only",
            ],
        },
        {
            "child_l2_id": "L2-memory-mechanism-evaluation-metrics",
            "label": "Memory Mechanism Evaluation & Metrics",
            "split_reason": "Separate scoring criteria, LLM-as-judge behavior, metrics, and correctness checks.",
            "assignment_criteria": [
                "llm-as-judge",
                "llm as judge",
                "metric",
                "scoring",
                "correctness",
                "judge",
                "quality",
            ],
        },
        {
            "child_l2_id": "L2-evaluation-datasets-ground-truth",
            "label": "Evaluation Datasets & Ground Truth",
            "split_reason": "Separate LOCOMO/MEMO/MIRIX dataset choice, ground truth, and multi-hop question design.",
            "assignment_criteria": [
                "locomo",
                "memo",
                "mirix",
                "dataset",
                "ground truth",
                "multi-hop",
                "multi hop",
                "question",
            ],
        },
    ],
}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _slug_from_l2_id(l2_id: str) -> str:
    clean = str(l2_id or "").strip()
    if clean.startswith("L2-"):
        clean = clean[3:]
    return clean or "unlabeled-topic"


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", str(text).lower())
        if token.strip()
    }


def _entry_text(entry: dict[str, Any]) -> str:
    return " ".join(
        [
            str(entry.get("summary", "") or ""),
            str(entry.get("content", "") or ""),
            str(entry.get("obj_id", "") or ""),
        ]
    )


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def child_l2_size_bucket(event_count: int) -> str:
    count = int(event_count or 0)
    if count < 3:
        return "needs_merge_review"
    if count <= 4:
        return "weak_child_l2"
    if count <= 25:
        return "ideal"
    if count <= 35:
        return "acceptable_but_watch"
    return "needs_split_review"


def _child_event_count(child: dict[str, Any]) -> int:
    try:
        count = int(child.get("event_count", 0) or 0)
    except (TypeError, ValueError):
        count = 0
    if count:
        return count
    linked = _as_list(child.get("linked_obj_ids"))
    if linked:
        return len(linked)
    return len(_as_list(child.get("timeline_digest")))


def _child_similarity(source: dict[str, Any], target: dict[str, Any]) -> tuple[float, list[str]]:
    source_label = _tokens(str(source.get("label", "") or ""))
    target_label = _tokens(str(target.get("label", "") or ""))
    source_criteria = _tokens(" ".join(str(x) for x in _as_list(source.get("assignment_criteria"))))
    target_criteria = _tokens(" ".join(str(x) for x in _as_list(target.get("assignment_criteria"))))
    source_timeline = _tokens(" ".join(_entry_text(x) for x in _as_list(source.get("timeline_digest")) if isinstance(x, dict)))
    target_timeline = _tokens(" ".join(_entry_text(x) for x in _as_list(target.get("timeline_digest")) if isinstance(x, dict)))
    source_meetings = {str(x) for x in _as_list(source.get("meeting_ids")) if str(x).strip()}
    target_meetings = {str(x) for x in _as_list(target.get("meeting_ids")) if str(x).strip()}

    label_score = _jaccard(source_label, target_label)
    criteria_score = _jaccard(source_criteria, target_criteria)
    timeline_score = _jaccard(source_timeline, target_timeline)
    meeting_score = _jaccard(source_meetings, target_meetings)
    score = (
        0.30 * label_score
        + 0.35 * criteria_score
        + 0.25 * timeline_score
        + 0.10 * meeting_score
    )
    reason_codes: list[str] = []
    if label_score >= 0.25:
        reason_codes.append("label_overlap")
    if criteria_score >= 0.25:
        reason_codes.append("assignment_criteria_overlap")
    if timeline_score >= 0.15:
        reason_codes.append("timeline_overlap")
    if meeting_score >= 0.20:
        reason_codes.append("meeting_overlap")
    return round(score, 4), reason_codes


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            return {}
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def _compact_timeline_digest(l2_node: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in _as_list(l2_node.get("timeline_digest")):
        if not isinstance(entry, dict):
            continue
        obj_id = str(entry.get("obj_id", "") or "").strip()
        if not obj_id:
            continue
        rows.append(
            {
                "obj_id": obj_id,
                "meeting_id": str(entry.get("meeting_id", "") or ""),
                "meeting_date": str(entry.get("meeting_date", "") or ""),
                "summary": str(entry.get("summary", "") or entry.get("content", "") or ""),
            }
        )
    return rows


def l2_promotion_metrics(
    l2_node: dict[str, Any],
    *,
    total_l1_count: int | None = None,
) -> dict[str, Any]:
    """Return stable size metrics for an active `l2_view` node."""
    linked_obj_ids = _as_list(l2_node.get("linked_obj_ids"))
    timeline_digest = _as_list(l2_node.get("timeline_digest"))
    meeting_ids = _as_list(l2_node.get("meeting_ids"))
    linked_l1_count = len(linked_obj_ids)
    total = int(total_l1_count or 0)
    l1_share = round(linked_l1_count / total, 4) if total > 0 else 0.0
    return {
        "linked_l1_count": linked_l1_count,
        "total_l1_count": total,
        "l1_share": l1_share,
        "timeline_digest_count": len(timeline_digest),
        "meeting_count": len(meeting_ids),
    }


def should_promote_l2(
    l2_node: dict[str, Any],
    *,
    total_l1_count: int | None = None,
    thresholds: dict[str, float] | None = None,
    validator_warning_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Decide whether an L2 node should enter L3 promotion review.

    This is a review gate. It never mutates `l2_node` and does not split topics.
    """
    limits = {**DEFAULT_L3_PROMOTION_THRESHOLDS, **(thresholds or {})}
    metrics = l2_promotion_metrics(l2_node, total_l1_count=total_l1_count)
    reason_codes: list[str] = []

    linked_l1_count = int(metrics["linked_l1_count"])
    if linked_l1_count >= int(limits["absolute_l1_threshold"]):
        reason_codes.append("too_many_l1_nodes")
    if (
        linked_l1_count >= int(limits["share_minimum_l1_count"])
        and float(metrics["l1_share"]) >= float(limits["share_threshold"])
    ):
        reason_codes.append("dominant_topic_share")

    warning_codes = set(validator_warning_codes or [])
    if "large_l2_topic" in warning_codes or "large_topic_review" in warning_codes:
        reason_codes.append("validator_large_topic_review")

    return {
        "promote": bool(reason_codes),
        "reason_codes": reason_codes,
        "metrics": metrics,
        "thresholds": limits,
    }


def build_l3_promotion_record(
    l2_node: dict[str, Any],
    *,
    child_l2_candidates: list[dict[str, Any]] | None = None,
    total_l1_count: int | None = None,
    thresholds: dict[str, float] | None = None,
    validator_warning_codes: list[str] | None = None,
    llm_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a sidecar promotion record for one overcrowded L2 node."""
    decision = should_promote_l2(
        l2_node,
        total_l1_count=total_l1_count,
        thresholds=thresholds,
        validator_warning_codes=validator_warning_codes,
    )
    l2_id = str(l2_node.get("l2_id", "") or "")
    proposed_l3_id = f"L3-{_slug_from_l2_id(l2_id)}"
    children = deepcopy(child_l2_candidates or [])
    child_ids = [
        str(child.get("child_l2_id", "") or "").strip()
        for child in children
        if isinstance(child, dict) and str(child.get("child_l2_id", "") or "").strip()
    ]
    min_child_count = int(decision["thresholds"]["min_child_l2_count"])
    status = "promotion_candidate" if decision["promote"] else "not_candidate"
    if decision["promote"] and len(child_ids) < min_child_count:
        status = "needs_split_review"

    return {
        "schema_version": L3_PROMOTION_SCHEMA_VERSION,
        "source": "long_term_l3_promotion",
        "source_l2_id": l2_id,
        "source_l2_label": str(l2_node.get("label", "") or ""),
        "proposed_l3_id": proposed_l3_id,
        "status": status,
        "reason_codes": decision["reason_codes"],
        "metrics": decision["metrics"],
        "thresholds": decision["thresholds"],
        "child_l2_candidates": children,
        "llm_usage": deepcopy(
            llm_usage
            or {
                "used": False,
                "stage": "none",
                "note": "Child L2 candidates came from deterministic defaults or human-reviewed input.",
            }
        ),
        "mapping": {
            "old_l2_id": l2_id,
            "new_l3_id": proposed_l3_id,
            "new_child_l2_ids": child_ids,
        },
    }


def child_l2_candidates_for_source_l2(l2_node: dict[str, Any]) -> list[dict[str, Any]]:
    """Return deterministic child L2 candidates for known overcrowded L2 topics."""
    l2_id = str(l2_node.get("l2_id", "") or "")
    candidates = DEFAULT_CHILD_L2_CANDIDATES_BY_SOURCE_L2_ID.get(l2_id, [])
    return deepcopy(candidates)


def _sanitize_child_l2_candidates(
    payload: dict[str, Any],
    *,
    source_l2_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Normalize an LLM taxonomy proposal into safe child L2 candidate records."""
    raw_children = _as_list(payload.get("child_l2_candidates"))
    seen: set[str] = set()
    children: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, raw_child in enumerate(raw_children):
        if not isinstance(raw_child, dict):
            errors.append(f"child[{index}] is not an object")
            continue
        child_id = str(raw_child.get("child_l2_id", "") or "").strip()
        label = str(raw_child.get("label", "") or "").strip()
        if not child_id:
            errors.append(f"child[{index}] missing child_l2_id")
            continue
        if not child_id.startswith("L2-"):
            child_id = f"L2-{child_id}"
        if child_id in seen:
            errors.append(f"duplicate child_l2_id: {child_id}")
            continue
        seen.add(child_id)
        children.append(
            {
                "child_l2_id": child_id,
                "label": label or child_id[3:].replace("-", " "),
                "split_reason": str(raw_child.get("split_reason", "") or ""),
                "assignment_criteria": [
                    str(item).strip()
                    for item in _as_list(raw_child.get("assignment_criteria"))
                    if str(item).strip()
                ],
                "source": "llm_child_taxonomy_proposal",
                "promoted_from_l2_id": source_l2_id,
            }
        )
    return children, {
        "errors": errors,
        "raw_child_count": len(raw_children),
        "accepted_child_count": len(children),
    }


def build_l3_promotion_sidecar(
    l2_view: dict[str, Any],
    *,
    total_l1_count: int | None = None,
    thresholds: dict[str, float] | None = None,
    generated_at_utc: str | None = None,
    child_taxonomy_proposer: ChildTaxonomyProposer | None = None,
    llm_source_l2_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Build a sidecar describing L2 topics that should be promoted to L3.

    The sidecar is derived from `l2_view` and never mutates L2 nodes or raw L1
    evidence. Known large topics can include deterministic child L2 candidates;
    unknown large topics are marked for split review.
    """
    nodes = l2_view.get("l2_nodes", [])
    if total_l1_count is None and isinstance(nodes, list):
        linked_ids: set[str] = set()
        for node in nodes:
            if not isinstance(node, dict):
                continue
            linked_ids.update(str(obj_id) for obj_id in _as_list(node.get("linked_obj_ids")))
        total_l1_count = len(linked_ids)
    promotions: list[dict[str, Any]] = []
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            decision = should_promote_l2(
                node,
                total_l1_count=total_l1_count,
                thresholds=thresholds,
            )
            if not decision["promote"]:
                continue
            child_candidates = child_l2_candidates_for_source_l2(node)
            llm_usage: dict[str, Any] = {
                "used": False,
                "stage": "none",
                "note": "Child L2 candidates came from deterministic defaults or human-reviewed input.",
            }
            source_l2_id = str(node.get("l2_id", "") or "")
            llm_targeted = llm_source_l2_ids is None or source_l2_id in llm_source_l2_ids
            if child_taxonomy_proposer is not None and not child_candidates and llm_targeted:
                try:
                    proposal = child_taxonomy_proposer(deepcopy(node))
                    proposed_children, proposal_validation = _sanitize_child_l2_candidates(
                        proposal if isinstance(proposal, dict) else {},
                        source_l2_id=source_l2_id,
                    )
                    if proposed_children:
                        child_candidates = proposed_children
                    llm_usage = {
                        "used": True,
                        "stage": "child_taxonomy_proposal",
                        "accepted": bool(proposed_children),
                        "fallback_used": not bool(proposed_children),
                        "validation": proposal_validation,
                    }
                except Exception as exc:
                    llm_usage = {
                        "used": True,
                        "stage": "child_taxonomy_proposal",
                        "accepted": False,
                        "fallback_used": True,
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        },
                    }
            promotions.append(
                build_l3_promotion_record(
                    node,
                    child_l2_candidates=child_candidates,
                    total_l1_count=total_l1_count,
                    thresholds=thresholds,
                    llm_usage=llm_usage,
                )
            )

    used_llm = any(
        bool(promotion.get("llm_usage", {}).get("used"))
        for promotion in promotions
        if isinstance(promotion, dict)
    )

    return {
        "schema_version": L3_PROMOTION_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc if generated_at_utc is not None else _utc_now_iso(),
        "source": "long_term_l2_view",
        "total_l1_count": int(total_l1_count or 0),
        "promotion_count": len(promotions),
        "llm_usage": {
            "used": used_llm,
            "stage": "child_taxonomy_proposal" if used_llm else "none",
        },
        "promotions": promotions,
    }


def _l2_nodes_by_id(l2_view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = l2_view.get("l2_nodes", [])
    if not isinstance(nodes, list):
        return {}
    output: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        l2_id = str(node.get("l2_id", "") or "").strip()
        if l2_id:
            output[l2_id] = node
    return output


def _score_child_candidate(entry: dict[str, Any], child: dict[str, Any]) -> int:
    text = _entry_text(entry).lower().replace("-", " ")
    score = 0
    for raw_hint in _as_list(child.get("assignment_criteria")):
        hint = str(raw_hint or "").strip().lower().replace("-", " ")
        if hint and hint in text:
            score += 3
    child_terms = _tokens(
        " ".join(
            [
                str(child.get("label", "") or ""),
                str(child.get("child_l2_id", "") or ""),
            ]
        ).replace("-", " ")
    )
    entry_terms = _tokens(text.replace("-", " "))
    score += len(child_terms & entry_terms)
    return score


def _assign_timeline_to_children(
    l2_node: dict[str, Any],
    child_candidates: list[dict[str, Any]],
    assignment_proposer: ChildAssignmentProposer | None = None,
    assignment_confidence_threshold: float = L3_ASSIGNMENT_CONFIDENCE_THRESHOLD,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    children = [
        child
        for child in child_candidates
        if isinstance(child, dict) and str(child.get("child_l2_id", "") or "").strip()
    ]
    if not children:
        return {}, {}

    assignments: dict[str, list[dict[str, Any]]] = {
        str(child["child_l2_id"]): [] for child in children
    }
    index: dict[str, dict[str, Any]] = {}
    timeline = [
        entry
        for entry in _as_list(l2_node.get("timeline_digest"))
        if isinstance(entry, dict) and str(entry.get("obj_id", "") or "").strip()
    ]
    child_lookup = {str(child["child_l2_id"]): child for child in children}
    child_ids = set(child_lookup)
    llm_assignments: dict[str, dict[str, Any]] = {}
    if assignment_proposer is not None:
        for raw_assignment in assignment_proposer(deepcopy(l2_node), deepcopy(children)):
            if not isinstance(raw_assignment, dict):
                continue
            obj_id = str(raw_assignment.get("obj_id", "") or "").strip()
            if obj_id:
                llm_assignments[obj_id] = raw_assignment

    for entry in timeline:
        obj_id = str(entry.get("obj_id", "") or "").strip()
        llm_assignment = llm_assignments.get(obj_id)
        manual_review = False
        llm_reason = ""
        if llm_assignment is not None:
            proposed_child_id = str(llm_assignment.get("child_l2_id", "") or "").strip()
            confidence = float(llm_assignment.get("confidence", 0.0) or 0.0)
            llm_reason = str(llm_assignment.get("reason", "") or "")
            if proposed_child_id in child_ids and confidence >= assignment_confidence_threshold:
                child_id = proposed_child_id
                score = confidence
                reason = "llm_assignment"
            else:
                scored = [
                    (_score_child_candidate(entry, child), str(child["child_l2_id"]))
                    for child in children
                ]
                scored.sort(key=lambda item: (-item[0], len(assignments[item[1]]), item[1]))
                fallback_score, child_id = scored[0]
                score = fallback_score
                manual_review = True
                reason = (
                    "llm_invalid_assignment_fallback"
                    if proposed_child_id not in child_ids
                    else "llm_low_confidence_fallback"
                )
        else:
            scored = [
                (_score_child_candidate(entry, child), str(child["child_l2_id"]))
                for child in children
            ]
            scored.sort(key=lambda item: (-item[0], len(assignments[item[1]]), item[1]))
            score, child_id = scored[0]
            reason = "criteria_match" if score > 0 else "balanced_fallback"
        assignments[child_id].append(deepcopy(entry))
        child = child_lookup[child_id]
        index[obj_id] = {
            "obj_id": obj_id,
            "source_l2_id": str(l2_node.get("l2_id", "") or ""),
            "l3_id": f"L3-{_slug_from_l2_id(str(l2_node.get('l2_id', '') or ''))}",
            "child_l2_id": child_id,
            "child_l2_label": str(child.get("label", "") or ""),
            "assignment_reason": reason,
            "assignment_score": score,
            "manual_review": manual_review,
        }
        if llm_assignment is not None:
            index[obj_id]["llm_assignment"] = {
                "child_l2_id": str(llm_assignment.get("child_l2_id", "") or ""),
                "confidence": float(llm_assignment.get("confidence", 0.0) or 0.0),
                "reason": llm_reason,
            }

    return assignments, index


def build_l3_materialization_sidecar(
    l2_view: dict[str, Any],
    l3_promotions: dict[str, Any],
    *,
    generated_at_utc: str | None = None,
    assignment_proposer: ChildAssignmentProposer | None = None,
    assignment_confidence_threshold: float = L3_ASSIGNMENT_CONFIDENCE_THRESHOLD,
) -> dict[str, Any]:
    """Materialize promotion candidates into L3 nodes with child L2 assignments.

    This creates sidecar views only. It does not mutate the active L2 view/index
    and does not touch raw L1 evidence.
    """
    l2_lookup = _l2_nodes_by_id(l2_view)
    l3_nodes: list[dict[str, Any]] = []
    l3_index: dict[str, dict[str, Any]] = {}

    for promotion in _as_list(l3_promotions.get("promotions")):
        if not isinstance(promotion, dict):
            continue
        if promotion.get("status") != "promotion_candidate":
            continue
        source_l2_id = str(promotion.get("source_l2_id", "") or "").strip()
        source_node = l2_lookup.get(source_l2_id)
        children = [
            child
            for child in _as_list(promotion.get("child_l2_candidates"))
            if isinstance(child, dict) and str(child.get("child_l2_id", "") or "").strip()
        ]
        if not source_node or len(children) < int(
            promotion.get("thresholds", {}).get("min_child_l2_count", 2)
        ):
            continue

        assignments, index_rows = _assign_timeline_to_children(
            source_node,
            children,
            assignment_proposer=assignment_proposer,
            assignment_confidence_threshold=assignment_confidence_threshold,
        )
        child_nodes: list[dict[str, Any]] = []
        for child in children:
            child_id = str(child["child_l2_id"])
            rows = assignments.get(child_id, [])
            linked_ids = [str(row.get("obj_id", "") or "") for row in rows]
            meeting_ids = sorted({str(row.get("meeting_id", "") or "") for row in rows if row.get("meeting_id")})
            child_nodes.append(
                {
                    "l2_id": child_id,
                    "label": str(child.get("label", "") or ""),
                    "source": "long_term_l3_materialized_child_l2",
                    "promoted_from_l2_id": source_l2_id,
                    "split_reason": str(child.get("split_reason", "") or ""),
                    "assignment_criteria": deepcopy(_as_list(child.get("assignment_criteria"))),
                    "current_state": (
                        f"This child L2 has {len(linked_ids)} linked L1 evidence "
                        f"object(s) split from {source_l2_id}."
                    ),
                    "linked_obj_ids": linked_ids,
                    "meeting_ids": meeting_ids,
                    "timeline_digest": rows,
                    "event_count": len(linked_ids),
                }
            )

        source_ids = {
            str(entry.get("obj_id", "") or "")
            for entry in _as_list(source_node.get("timeline_digest"))
            if isinstance(entry, dict) and str(entry.get("obj_id", "") or "").strip()
        }
        assigned_ids = set(index_rows)
        l3_id = str(promotion.get("proposed_l3_id", "") or "")
        manual_review_count = sum(1 for row in index_rows.values() if row.get("manual_review"))
        l3_nodes.append(
            {
                "l3_id": l3_id,
                "label": str(promotion.get("source_l2_label", "") or ""),
                "source": "long_term_l3_materialization",
                "promoted_from_l2_id": source_l2_id,
                "reason_codes": deepcopy(_as_list(promotion.get("reason_codes"))),
                "metrics": deepcopy(promotion.get("metrics", {})),
                "child_l2_nodes": child_nodes,
                "coverage": {
                    "source_l1_count": len(source_ids),
                    "assigned_l1_count": len(assigned_ids),
                    "unassigned_l1_count": len(source_ids - assigned_ids),
                },
                "manual_review_count": manual_review_count,
            }
        )
        for obj_id, row in index_rows.items():
            row["l3_id"] = l3_id
            l3_index[obj_id] = row

    used_assignment_llm = assignment_proposer is not None and bool(l3_nodes)
    return {
        "schema_version": L3_PROMOTION_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc if generated_at_utc is not None else _utc_now_iso(),
        "source": "long_term_l3_materialization",
        "materialized_l3_count": len(l3_nodes),
        "l3_nodes": l3_nodes,
        "l3_index": dict(sorted(l3_index.items())),
        "llm_usage": {
            "used": used_assignment_llm,
            "stage": "l1_child_l2_assignment" if used_assignment_llm else "none",
            "note": (
                "LLM-assisted child L2 assignments were validated and fell back "
                "deterministically when invalid or low-confidence."
                if used_assignment_llm
                else "Default materialization uses deterministic assignment criteria or human-reviewed child candidates."
            ),
        },
    }


def build_l2_merge_review_sidecar(
    l3_view: dict[str, Any],
    *,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a sidecar review queue for tiny or oversized materialized child L2s.

    This is review-only. It recommends possible sibling merge targets but does
    not rewrite child assignments, the active L2 view, or raw L1 evidence.
    """
    merge_reviews: list[dict[str, Any]] = []
    child_size_summary: list[dict[str, Any]] = []

    for parent in _as_list(l3_view.get("l3_nodes")):
        if not isinstance(parent, dict):
            continue
        parent_l3_id = str(parent.get("l3_id", "") or "")
        children = [
            child
            for child in _as_list(parent.get("child_l2_nodes"))
            if isinstance(child, dict) and str(child.get("l2_id", "") or "").strip()
        ]
        for child in children:
            child_id = str(child.get("l2_id", "") or "")
            event_count = _child_event_count(child)
            bucket = child_l2_size_bucket(event_count)
            child_size_summary.append(
                {
                    "parent_l3_id": parent_l3_id,
                    "child_l2_id": child_id,
                    "label": str(child.get("label", "") or ""),
                    "event_count": event_count,
                    "size_bucket": bucket,
                }
            )

            if bucket not in {"needs_merge_review", "weak_child_l2", "needs_split_review"}:
                continue

            reason_codes: list[str] = []
            action = "manual_review"
            if bucket == "needs_merge_review":
                reason_codes.append("too_few_l1_nodes")
                action = "watch_until_more_evidence"
            elif bucket == "weak_child_l2":
                reason_codes.append("weak_child_l2")
                action = "watch_until_more_evidence"
            else:
                reason_codes.append("too_many_l1_nodes")
                action = "split_review"

            best_target: dict[str, Any] | None = None
            best_score = 0.0
            best_reasons: list[str] = []
            if bucket in {"needs_merge_review", "weak_child_l2"}:
                for sibling in children:
                    sibling_id = str(sibling.get("l2_id", "") or "")
                    if sibling_id == child_id:
                        continue
                    score, sibling_reasons = _child_similarity(child, sibling)
                    if score > best_score:
                        best_score = score
                        best_target = sibling
                        best_reasons = sibling_reasons
                if best_target is not None and best_score >= 0.18:
                    reason_codes.extend(best_reasons or ["highest_sibling_similarity"])
                    action = "merge_candidate" if bucket == "needs_merge_review" else "merge_review"
                else:
                    best_target = None
                    reason_codes.append("low_sibling_similarity")

            merge_reviews.append(
                {
                    "parent_l3_id": parent_l3_id,
                    "source_child_l2_id": child_id,
                    "source_child_l2_label": str(child.get("label", "") or ""),
                    "source_event_count": event_count,
                    "recommended_target_child_l2_id": (
                        str(best_target.get("l2_id", "") or "") if best_target else ""
                    ),
                    "recommended_target_label": (
                        str(best_target.get("label", "") or "") if best_target else ""
                    ),
                    "similarity_score": round(best_score, 4),
                    "reason_codes": sorted(set(reason_codes)),
                    "action": action,
                }
            )

    return {
        "schema_version": L3_PROMOTION_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc if generated_at_utc is not None else _utc_now_iso(),
        "source": "long_term_l3_child_l2_merge_review",
        "merge_review_count": len(merge_reviews),
        "merge_reviews": merge_reviews,
        "child_size_summary": child_size_summary,
    }


def build_child_taxonomy_prompt(l2_node: dict[str, Any]) -> str:
    """Build the optional prompt for an LLM to propose child L2 taxonomy.

    This prompt only includes compact evidence already linked to the promoted
    L2. It never asks the model to rewrite raw L1 evidence.
    """
    payload = {
        "l2_id": l2_node.get("l2_id", ""),
        "label": l2_node.get("label", ""),
        "current_state": l2_node.get("current_state", ""),
        "linked_l1_count": len(_as_list(l2_node.get("linked_obj_ids"))),
        "timeline_digest": _compact_timeline_digest(l2_node),
    }
    return (
        "Propose 2-5 child L2 topics for splitting this overcrowded L2. "
        "Return JSON with child_l2_id, label, split_reason, and assignment_criteria. "
        "Do not modify raw L1 evidence.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def build_child_assignment_prompt(
    l2_node: dict[str, Any],
    child_l2_candidates: list[dict[str, Any]],
) -> str:
    """Build the optional prompt for assigning promoted L2 L1 rows to child L2s."""
    payload = {
        "source_l2": {
            "l2_id": l2_node.get("l2_id", ""),
            "label": l2_node.get("label", ""),
        },
        "child_l2_candidates": [
            {
                "child_l2_id": child.get("child_l2_id", ""),
                "label": child.get("label", ""),
                "assignment_criteria": _as_list(child.get("assignment_criteria")),
            }
            for child in child_l2_candidates
            if isinstance(child, dict)
        ],
        "l1_evidence": _compact_timeline_digest(l2_node),
    }
    return (
        "Assign each listed L1 evidence item to exactly one child L2. "
        "Return exactly one assignment per listed L1. "
        "Use only the provided child_l2_id values. "
        "Do not modify raw L1 evidence.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def create_gemini_child_taxonomy_proposer(
    *,
    api_key: str | list[str],
    model_name: str,
) -> ChildTaxonomyProposer:
    """Create a Gemini-backed proposer for child L2 taxonomy."""
    from gemini_clients import create_gemini_client

    client = create_gemini_client(api_key)

    def propose(l2_node: dict[str, Any]) -> dict[str, Any]:
        response = client.models.generate_content(
            model=model_name,
            contents=build_child_taxonomy_prompt(l2_node),
            config={
                "temperature": 0.1,
                "response_mime_type": "application/json",
                "response_json_schema": CHILD_TAXONOMY_SCHEMA,
            },
        )
        return _extract_json_object(response.text or "")

    return propose


def create_gemini_child_assignment_proposer(
    *,
    api_key: str | list[str],
    model_name: str,
) -> ChildAssignmentProposer:
    """Create a Gemini-backed proposer for L1 -> child L2 assignments."""
    from gemini_clients import create_gemini_client

    client = create_gemini_client(api_key)

    def propose(
        l2_node: dict[str, Any],
        child_l2_candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        response = client.models.generate_content(
            model=model_name,
            contents=build_child_assignment_prompt(l2_node, child_l2_candidates),
            config={
                "temperature": 0.1,
                "response_mime_type": "application/json",
                "response_json_schema": CHILD_ASSIGNMENT_SCHEMA,
            },
        )
        data = _extract_json_object(response.text or "")
        assignments = data.get("assignments", [])
        return assignments if isinstance(assignments, list) else []

    return propose
