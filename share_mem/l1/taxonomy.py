"""L1 taxonomy definitions and compatibility helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

TAXONOMY_V1 = "v1"
TAXONOMY_V2_MEMORY_ROLES = "v2-memory-roles"

LEGACY_L1_TYPE_ORDER = (
    "decision",
    "todo",
    "method_change",
    "result",
    "argument",
    "open_question",
)
LEGACY_L1_TYPES = set(LEGACY_L1_TYPE_ORDER)

V2_MEMORY_ROLE_TYPE_ORDER = (
    "decision",
    "action_item",
    "open_issue",
    "proposal",
    "argument",
    "finding",
    "approach_change",
)
V2_MEMORY_ROLE_TYPES = set(V2_MEMORY_ROLE_TYPE_ORDER)

LEGACY_TYPE_DEFINITIONS = {
    "decision": "high-level conclusion, adoption, rejection, focus choice, or resolved direction",
    "todo": "explicit next step, assigned follow-up, pending action, or unresolved work item with execution expectation",
    "method_change": "change in method, process, procedure, strategy, data handling, or evaluation approach",
    "result": "observation, outcome, finding, experiment result, failure mode, comparison, or evidence report",
    "argument": "reasoning, tradeoff, constraint, or justification that explains why a decision or method direction is preferred",
    "open_question": "unresolved research question, blocker, uncertainty, or decision point that still needs clarification",
}

V2_TYPE_DEFINITIONS = {
    "decision": "adopted, rejected, resolved, or materially revised conclusion that changes project state",
    "action_item": "explicit follow-up, assigned work, experiment to run, implementation task, or check with execution expectation",
    "open_issue": "unresolved blocker, design issue, uncertainty, research question, or decision point that still needs clarification",
    "proposal": "suggested option, alternative, hypothesis, design, or plan that has not yet been adopted as a decision",
    "argument": "reasoning, tradeoff, constraint, evidence interpretation, or justification for or against a proposal or decision",
    "finding": "stable observation, experiment result, comparison, failure mode, literature finding, data-quality finding, or evidence report",
    "approach_change": "adopted change in method, process, architecture, retrieval strategy, schema, data handling, or evaluation approach",
}

LEGACY_COMPATIBILITY_DESCRIPTIONS = {
    "decision": "old decision: accepted or resolved project conclusion",
    "todo": "old todo: explicit or implied executable follow-up",
    "method_change": "old method_change: method, process, architecture, data, or evaluation change",
    "result": "old result: observation, outcome, finding, comparison, or evidence report",
    "open_question": "old open_question: unresolved question, blocker, issue, or uncertainty",
    "argument": "old argument: rationale, tradeoff, constraint, or decision-supporting reasoning",
}

_DEFAULT_V2_TO_LEGACY = {
    "decision": "decision",
    "action_item": "todo",
    "open_issue": "open_question",
    "proposal": "result",
    "argument": "argument",
    "finding": "result",
    "approach_change": "method_change",
}


def normalize_taxonomy(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if text in {"", "v1", "legacy", "legacy-v1"}:
        return TAXONOMY_V1
    if text in {"v2", "v2-memory-roles", "memory-roles"}:
        return TAXONOMY_V2_MEMORY_ROLES
    raise ValueError(f"Unsupported L1 taxonomy: {value}")


def type_order_for_taxonomy(taxonomy: str | None) -> tuple[str, ...]:
    normalized = normalize_taxonomy(taxonomy)
    if normalized == TAXONOMY_V2_MEMORY_ROLES:
        return V2_MEMORY_ROLE_TYPE_ORDER
    return LEGACY_L1_TYPE_ORDER


def type_set_for_taxonomy(taxonomy: str | None) -> set[str]:
    return set(type_order_for_taxonomy(taxonomy))


def type_definitions_for_taxonomy(taxonomy: str | None) -> dict[str, str]:
    normalized = normalize_taxonomy(taxonomy)
    if normalized == TAXONOMY_V2_MEMORY_ROLES:
        return V2_TYPE_DEFINITIONS
    return LEGACY_TYPE_DEFINITIONS


def default_legacy_type_for_v2(obj_type: str) -> str:
    clean = str(obj_type or "").strip().lower()
    return _DEFAULT_V2_TO_LEGACY.get(clean, "result")


def normalize_legacy_type(value: str | None, *, obj_type: str = "") -> str:
    clean = str(value or "").strip().lower()
    if clean in LEGACY_L1_TYPES:
        return clean
    if obj_type:
        return default_legacy_type_for_v2(obj_type)
    return "result"


def candidate_schema_for_taxonomy(
    taxonomy: str | None,
    *,
    include_legacy_type: bool = False,
    max_items: int = 6,
    require_type: bool | None = None,
) -> dict[str, Any]:
    """Return a structured-output schema for L1 candidates.

    v1 keeps the historical typed-agent shape by default: the agent is scoped
    to one type and does not need to echo it. v2 includes `type` so logs and
    parsed artifacts are self-describing for side-by-side comparison.
    """

    normalized = normalize_taxonomy(taxonomy)
    include_type = (
        normalized == TAXONOMY_V2_MEMORY_ROLES if require_type is None else require_type
    )
    properties: dict[str, Any] = {
        "source_unit_ids": {"type": "array", "items": {"type": "string"}},
        "content": {
            "type": "string",
            "description": (
                "Human-facing L1 memory summary. Write canonical share_mem L1 "
                "content in Traditional Chinese, even when bounded idea units are "
                "English intermediate summaries; keep technical anchors such as "
                "RAG, L1/L2/L3, API, topic lifecycle, and manager-agent in English "
                "when those terms are used."
            ),
        },
        "importance": {"type": "number"},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "related_topics": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Machine-facing topic keys. Use concise English normalized labels, "
                "prefer lowercase words separated by spaces, and do not translate "
                "these labels into Chinese."
            ),
        },
    }
    required = [
        "source_unit_ids",
        "content",
        "importance",
        "confidence",
        "rationale",
        "related_topics",
    ]
    if include_type:
        properties = {
            "type": {
                "type": "string",
                "enum": sorted(type_set_for_taxonomy(normalized)),
            },
            **properties,
        }
        required = ["type", *required]
    if include_legacy_type:
        properties["legacy_type"] = {
            "type": "string",
            "enum": sorted(LEGACY_L1_TYPES),
        }
        required.append("legacy_type")

    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "maxItems": max_items,
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            }
        },
        "required": ["candidates"],
        "additionalProperties": False,
    }


def fallback_candidate_schema_for_taxonomy(
    taxonomy: str | None,
    *,
    include_legacy_type: bool = False,
    max_items: int = 3,
) -> dict[str, Any]:
    return candidate_schema_for_taxonomy(
        taxonomy,
        include_legacy_type=include_legacy_type,
        max_items=max_items,
        require_type=True,
    )


def bridge_memory_object_schema_for_taxonomy(
    base_schema: dict[str, Any],
    taxonomy: str | None,
    *,
    include_legacy_type: bool = False,
) -> dict[str, Any]:
    schema = deepcopy(base_schema)
    item = schema["properties"]["memory_objects"]["items"]
    item["properties"]["type"]["enum"] = sorted(type_set_for_taxonomy(taxonomy))
    if include_legacy_type:
        item["properties"]["legacy_type"] = {
            "type": "string",
            "enum": sorted(LEGACY_L1_TYPES),
        }
        if "legacy_type" not in item["required"]:
            item["required"].append("legacy_type")
    return schema
