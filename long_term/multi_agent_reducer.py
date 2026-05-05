"""Conflict resolution and final L1 patch reduction for multi-agent output."""

from __future__ import annotations

from typing import Any

from importance import MIN_IMPORTANCE_THRESHOLD, calibrate_l1_importance
from multi_agent_state import ConflictDecision, GroundedCandidate
from multi_agent_tools import clamp_float, jaccard, tokenize, unique_strings

TYPE_PRIORITY = {
    "method_change": 3,
    "decision": 2,
    "argument": 1,
    "open_question": 1,
    "result": 1,
    "todo": 1,
}

VIEWPOINT_EPISODE_GAP_LINES = 10
VIEWPOINT_RECURRENCE_BONUS_BY_EPISODES = {
    2: 0.02,
    3: 0.04,
    4: 0.06,
}
VIEWPOINT_RECURRENCE_TYPE_CAPS = {
    "decision": 0.93,
    "method_change": 0.93,
    "result": 0.84,
    "todo": 0.84,
    "open_question": 0.80,
    "argument": 0.78,
}

_FOLLOWUP_TASK_MARKERS = (
    "assess",
    "compare",
    "conduct",
    "confirm",
    "determine",
    "evaluate",
    "explore",
    "investigate",
    "review",
    "research",
    "look into",
    "try",
    "評估",
    "比較",
    "確認",
    "研究",
    "調查",
    "檢查",
    "看看",
    "看一下",
    "嘗試",
    "探索",
)

_COMMITTED_CHANGE_MARKERS = (
    "adopt",
    "adopted",
    "decided",
    "changed",
    "implement",
    "implemented",
    "switch",
    "switched",
    "will use",
    "shifted from",
    "moving from",
    "decided to",
    "team decided",
    "project will",
    "uses gemini",
    "uses tool calling",
    "uses `read`",
    "uses read",
    "uses write",
    "決定採用",
    "決定使用",
    "決定將",
    "決定維持",
    "決定進行",
    "決定探索",
    "將聚焦",
    "已決定",
    "團隊決定",
    "專案採用",
    "團隊採用",
    "已採用",
    "改用",
    "改為",
    "改成",
    "已改",
    "實作",
    "導入",
    "將採用",
    "將使用",
    "將實作",
)

_DESCRIPTIVE_STRUCTURE_MARKERS = (
    "defined structure",
    "defined as",
    "has a defined structure",
    "defined to include",
    "final output",
    "output format",
    "is structured",
    "is organized",
    "organized into",
    "consists of",
    "field",
    "fields",
    "hierarchy",
    "tree-like",
    "contains",
    "include",
    "includes",
    "collection of memory objects",
    "memory object is structured",
    "被設計為",
    "被組織",
    "被定義為",
    "最終輸出",
    "最終產出",
    "結構",
    "包含",
    "欄位",
    "層級",
    "樹狀",
)

_EVALUATION_DATASET_MARKERS = (
    "dataset",
    "資料集",
)

_DEMO_PLAN_MARKERS = (
    "demo",
    "demonstration",
    "exhibition",
    "展示",
    "示範",
    "演示",
    "展覽",
)

_PROPOSAL_MARKERS = (
    "proposed",
    "proposal",
    "suggested",
    "提議",
    "提出",
    "建議",
)

_GOAL_STATEMENT_MARKERS = (
    "goal is",
    "goal for",
    "aim is",
    "objective is",
    "target is",
    "目標是",
    "目標為",
    "目的在於",
)

_UNRESOLVED_TASK_MARKERS = (
    "unresolved task",
    "unresolved question",
    "open task",
    "needs to be defined",
    "needs to define",
    "needs to decide",
    "need to define",
    "need to decide",
    "still needs clarification",
    "has not been decided",
    "尚未確定",
    "尚未決定",
    "待解決",
    "待釐清",
    "需要定義",
    "需要決定",
    "需要釐清",
)

_DURABLE_MARKERS = (
    "adopt",
    "decide",
    "decision",
    "change",
    "method",
    "strategy",
    "architecture",
    "pipeline",
    "implement",
    "evaluate",
    "baseline",
    "memory",
    "retrieval",
    "tool calling",
    "long-term",
    "short-term",
    "決定",
    "採用",
    "改",
    "方法",
    "策略",
    "架構",
    "流程",
    "實作",
    "評估",
    "記憶",
    "長期",
    "短期",
    "檢索",
)


def _as_candidate_dict(candidate: GroundedCandidate | dict[str, Any]) -> dict[str, Any]:
    if isinstance(candidate, dict):
        return dict(candidate)
    return {
        "candidate_id": candidate.candidate_id,
        "type": candidate.type,
        "source_unit_ids": candidate.source_unit_ids,
        "content": candidate.content,
        "importance": candidate.importance,
        "confidence": candidate.confidence,
        "rationale": candidate.rationale,
        "related_topics": candidate.related_topics,
        "extraction_scope": candidate.extraction_scope,
        "segment_ids": candidate.segment_ids,
        "evidence_lines": candidate.evidence_lines,
        "evidence_quote": candidate.evidence_quote,
        "support_score": candidate.support_score,
        "grounding_note": candidate.grounding_note,
        "source_unit_completeness": candidate.source_unit_completeness,
        "source_unit_uncertainty_notes": candidate.source_unit_uncertainty_notes,
    }


def _same_span(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_lines = set(left.get("evidence_lines", []))
    right_lines = set(right.get("evidence_lines", []))
    if not left_lines or not right_lines:
        return False
    return bool(left_lines & right_lines)


def _merge_candidate(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    preferred, other = left, right
    if TYPE_PRIORITY.get(str(right.get("type", "")), 0) > TYPE_PRIORITY.get(
        str(left.get("type", "")),
        0,
    ):
        preferred, other = right, left
    merged = dict(preferred)
    merged["candidate_id"] = f"{preferred.get('candidate_id')}+{other.get('candidate_id')}"
    merged["importance"] = max(
        clamp_float(preferred.get("importance", 0.5)),
        clamp_float(other.get("importance", 0.5)),
    )
    merged["confidence"] = max(
        clamp_float(preferred.get("confidence", 0.5)),
        clamp_float(other.get("confidence", 0.5)),
    )
    merged["related_topics"] = unique_strings(
        list(preferred.get("related_topics", [])) + list(other.get("related_topics", []))
    )
    merged["source_unit_ids"] = unique_strings(
        list(preferred.get("source_unit_ids", [])) + list(other.get("source_unit_ids", []))
    )
    merged["source_unit_completeness"] = unique_strings(
        list(preferred.get("source_unit_completeness", []))
        + list(other.get("source_unit_completeness", []))
    )
    merged["source_unit_uncertainty_notes"] = unique_strings(
        list(preferred.get("source_unit_uncertainty_notes", []))
        + list(other.get("source_unit_uncertainty_notes", []))
    )
    merged["segment_ids"] = unique_strings(
        list(preferred.get("segment_ids", [])) + list(other.get("segment_ids", []))
    )
    merged["evidence_lines"] = sorted(
        set(preferred.get("evidence_lines", [])) | set(other.get("evidence_lines", []))
    )
    if len(str(other.get("evidence_quote", ""))) > len(
        str(preferred.get("evidence_quote", ""))
    ):
        merged["evidence_quote"] = other.get("evidence_quote", "")
    merged["resolution_note"] = "merged as semantically redundant cross-type candidates"
    return merged


def _contains_durable_marker(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in _DURABLE_MARKERS)


def _looks_like_followup_task(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in _FOLLOWUP_TASK_MARKERS)


def _looks_like_committed_change(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in _COMMITTED_CHANGE_MARKERS)


def _looks_like_descriptive_structure(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in _DESCRIPTIVE_STRUCTURE_MARKERS)


def _looks_like_evaluation_dataset_plan(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in _EVALUATION_DATASET_MARKERS)


def _looks_like_demo_plan(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in _DEMO_PLAN_MARKERS)


def _looks_like_proposal(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in _PROPOSAL_MARKERS)


def _looks_like_goal_statement(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in _GOAL_STATEMENT_MARKERS)


def _looks_like_unresolved_task(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in _UNRESOLVED_TASK_MARKERS)


def _has_any(text: str, markers: tuple[str, ...] | list[str] | set[str]) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in markers)


def _concept_keys(row: dict[str, Any]) -> set[str]:
    """Coarse semantic keys used only for deterministic final de-duplication."""
    content = str(row.get("content", ""))
    topics = " ".join(str(topic) for topic in row.get("related_topics", []))
    text = f"{content}\n{topics}".lower()
    keys: set[str] = set()

    if _has_any(text, ("whisperx", "speaker turn", "speaker turns", "人工校對", "說話者")):
        keys.add("transcript_preparation")
    if _has_any(text, ("global vector", "全域向量", "全球向量")):
        keys.add("global_vector_alternative")
    if _has_any(text, ("information entropy", "資訊熵", "entropy")):
        keys.add("entropy_segmentation")
    if _has_any(text, ("literature review", "文獻回顧")) and _has_any(
        text,
        ("segmentation", "分段", "切分", "look-ahead", "前瞻", "entropy", "資訊熵"),
    ):
        keys.add("entropy_literature_review")
    if _has_any(text, ("function calling", "tool calling", "tool-calling", "工具調用", "函式呼叫")) and _has_any(
        text,
        ("read", "line", "chunk", "逐字稿", "讀取", "行數", "分塊"),
    ):
        keys.add("dynamic_tool_calling_read")
    if _has_any(text, ("read", "`read`", "write", "`write`")) and _has_any(
        text,
        ("memory database", "memory db", "記憶體資料庫", "記憶資料庫"),
    ):
        keys.add("read_write_memory_update")
    if _has_any(text, ("preprocess", "pre-processing", "預處理")) and _has_any(
        text,
        ("idea unit", "idea units", "想法單元"),
    ):
        keys.add("idea_unit_preprocess")
    if _has_any(text, ("idea unit", "idea units", "想法單元")) and _has_any(
        text,
        ("same topic", "continuation", "完整", "連續", "延續", "分割"),
    ):
        keys.add("idea_unit_grouping")
    if _has_any(text, ("incoming idea", "傳入的想法", "每個傳入")) and _has_any(
        text,
        ("short-term", "long-term", "短期", "長期"),
    ):
        keys.add("memory_update_router")
    if _has_any(text, ("fixed-size", "fixed size", "sentence-by-sentence", "逐句", "固定大小")) and _has_any(
        text,
        ("baseline", "baselines", "evaluation", "評估", "比較"),
    ):
        keys.add("unit_generation_evaluation")
    if (
        _has_any(text, ("rag",))
        and _has_any(
            text,
            (
                "compare",
                "comparison",
                "contrast",
                "baseline",
                "evaluation",
                "demo",
                "demonstration",
                "比較",
                "評估",
                "展示",
                "示範",
            ),
        )
        and _has_any(
            text,
            ("memory structure", "short-term", "long-term", "長短期", "長期記憶", "短期記憶"),
        )
    ):
        keys.add("rag_baseline_comparison")
    if _has_any(text, ("memory object", "memory objects", "記憶物件")) and _has_any(
        text,
        (
            "type",
            "content",
            "evidence",
            "related topics",
            "field",
            "fields",
            "欄位",
            "final output",
            "最終輸出",
            "最終產出",
        ),
    ):
        keys.add("memory_object_schema")
    if _has_any(text, ("l1", "l2", "l3")) and _has_any(
        text,
        ("hierarchy", "tree", "summary", "summarized", "層級", "樹", "摘要"),
    ):
        keys.add("l123_hierarchy")
    if _has_any(text, ("short-term", "long-term", "短期", "長期")) and _has_any(
        text,
        ("separate", "separation", "distinguish", "區分", "分開", "獨立"),
    ):
        keys.add("memory_separation")
    if _has_any(text, ("timeline", "時間軸")):
        keys.add("retrieval_timeline")
    if _has_any(text, ("flat", "扁平")) and _has_any(text, ("tree", "樹")):
        keys.add("flat_memory_tree")
    if _has_any(text, ("forgetting", "forgotten", "forget", "遺忘")) and _has_any(
        text,
        ("relevancy", "relevance", "importance", "decay", "衰減", "重要性", "相關性"),
    ):
        keys.add("forgetting_mechanism")
    if _has_any(text, ("dataset", "資料集")) and _has_any(
        text,
        ("demo", "demonstration", "展示", "示範", "演示"),
    ):
        keys.add("demo_dataset_strategy")
    if _has_any(text, ("simulate", "simulated", "generate", "生成", "模擬", "對話環節")) and _has_any(
        text,
        ("demo", "demonstration", "展示", "示範", "演示", "rag"),
    ):
        keys.add("demo_dataset_strategy")
    if _has_any(text, ("exhibition", "展覽", "發表")) and _has_any(
        text,
        ("demo", "idea unit", "展示", "想法單元"),
    ):
        keys.add("exhibition_scope")
    if _has_any(text, ("large time span", "time span", "long time", "時間跨度")):
        keys.add("long_span_goal")
    return keys


def _viewpoint_keys(row: dict[str, Any]) -> set[str]:
    """Stricter identity keys for recurrence-based importance only.

    Concept keys can be broad enough for de-duplication. Recurrence needs a
    tighter notion of "same viewpoint" so a repeated domain topic does not
    inflate unrelated objects.
    """
    content = str(row.get("content", ""))
    topics = " ".join(str(topic) for topic in row.get("related_topics", []))
    text = f"{content}\n{topics}".lower()
    keys: set[str] = set()

    if (
        _has_any(text, ("fixed-size", "fixed size", "sentence-by-sentence", "逐句", "固定大小"))
        and _has_any(text, ("baseline", "baselines", "compare", "comparison", "評估", "比較"))
    ):
        keys.add("compare_unit_generation_baselines")

    if (
        _has_any(text, ("rag",))
        and _has_any(text, ("compare", "comparison", "contrast", "baseline", "比較", "展示", "demo"))
        and _has_any(text, ("memory", "記憶", "long-term", "short-term", "長期", "短期"))
    ):
        keys.add("compare_memory_architecture_with_rag")

    if (
        _has_any(text, ("short-term", "long-term", "短期", "長期"))
        and _has_any(
            text,
            (
                "separate",
                "separation",
                "differentiate",
                "distinguish",
                "storage method",
                "detail level",
                "detailed",
                "concise",
                "區分",
                "分開",
                "儲存",
                "詳細",
                "精簡",
            ),
        )
        and not _has_any(text, ("rag", "baseline", "demo", "展示", "比較", "評估"))
    ):
        keys.add("short_long_memory_storage_distinction")

    if (
        _has_any(text, ("forgetting", "forgotten", "forget", "fade out", "decay", "遺忘", "忘記"))
        and _has_any(
            text,
            (
                "relevancy",
                "relevance",
                "importance",
                "threshold",
                "weight",
                "重要性",
                "相關性",
                "權重",
                "衰減",
            ),
        )
    ):
        keys.add("long_term_forgetting_decay")

    if (
        _has_any(
            text,
            (
                "own meeting",
                "meeting transcripts",
                "primary dataset",
                "我們自己的dataset",
                "自己的會議",
                "會議資料集",
            ),
        )
        and _has_any(text, ("demo", "demonstration", "evaluate", "evaluation", "展示", "示範", "評估"))
    ):
        keys.add("demo_own_meeting_dataset")

    if (
        _has_any(text, ("idea unit", "idea units", "想法單元"))
        and _has_any(text, ("pack", "merge", "higher-level", "overlap", "打包", "合併", "重疊"))
        and not _has_any(text, ("demo", "demonstration", "exhibition", "五月", "專題展", "展示"))
    ):
        keys.add("idea_unit_cross_span_merging")

    if (
        _has_any(text, ("idea unit", "idea units", "想法單元"))
        and _has_any(text, ("demo", "demonstration", "exhibition", "五月", "專題展", "展示"))
    ):
        keys.add("idea_unit_demo_scope")

    if (
        _has_any(text, ("memory object", "memory objects", "記憶物件"))
        and _has_any(text, ("type", "content", "evidence", "related topics", "欄位", "證據"))
    ):
        keys.add("memory_object_schema_fields")

    return keys


def _normalize_candidate_type(
    obj_type: str,
    *,
    content: str,
    evidence: str,
) -> str:
    del evidence
    if obj_type in {"decision", "method_change", "argument", "result"} and _looks_like_unresolved_task(
        content
    ):
        return "todo"
    if (
        obj_type in {"decision", "method_change"}
        and _looks_like_followup_task(content)
        and not _looks_like_committed_change(content)
    ):
        return "todo"
    if (
        obj_type == "decision"
        and _looks_like_proposal(content)
        and not _looks_like_committed_change(content)
    ):
        return "result"
    if (
        obj_type in {"decision", "method_change"}
        and _looks_like_descriptive_structure(content)
        and not _looks_like_committed_change(content)
    ):
        return "result"
    if (
        obj_type == "todo"
        and _looks_like_descriptive_structure(content)
        and not _looks_like_followup_task(content)
    ):
        return "result"
    if obj_type == "todo" and _looks_like_goal_statement(content):
        return "decision" if _contains_durable_marker(content) else "result"
    if obj_type == "todo" and _looks_like_demo_plan(content) and _looks_like_committed_change(content):
        return "decision"
    if obj_type == "method_change" and _looks_like_evaluation_dataset_plan(content):
        return "decision" if _looks_like_committed_change(content) else "todo"
    if obj_type == "method_change" and _looks_like_demo_plan(content):
        return "decision" if _looks_like_committed_change(content) else "todo"
    if (
        obj_type == "method_change"
        and _looks_like_proposal(content)
        and not _looks_like_committed_change(content)
    ):
        return "result"
    return obj_type


def _source_unit_quality_warnings(candidate: dict[str, Any]) -> set[str]:
    warnings = {
        str(value or "").strip()
        for value in candidate.get("unit_quality_warnings", [])
        if str(value or "").strip()
    }
    completeness_values = {
        str(value or "").strip().lower()
        for value in candidate.get("source_unit_completeness", [])
        if str(value or "").strip()
    }
    if completeness_values & {"fallback", "compacted"}:
        warnings.add("validator_repaired_source_unit")
    if completeness_values & {
        "partial",
        "incomplete",
        "uncertain",
        "unknown",
        "fallback",
        "compacted",
    }:
        warnings.add("uncertain_source_unit")
    if candidate.get("source_unit_uncertainty_notes"):
        warnings.add("source_unit_uncertainty_note")
    return warnings


def _multi_agent_importance(
    candidate: dict[str, Any],
    *,
    obj_type: str,
    content: str,
    evidence: str,
    related_topics: list[str],
) -> float:
    model_score = clamp_float(candidate.get("importance", 0.5))
    score = calibrate_l1_importance(
        obj_type,
        model_score,
        content=content,
        evidence=evidence,
        related_topics=related_topics,
    )
    confidence = clamp_float(candidate.get("confidence", 0.5))
    support_score = clamp_float(candidate.get("support_score", 0.0), fallback=0.0)
    evidence_lines = candidate.get("evidence_lines", [])
    evidence_line_count = len(evidence_lines) if isinstance(evidence_lines, list) else 0
    token_count = len(tokenize(content))
    durable_marker = _contains_durable_marker(f"{content}\n{' '.join(related_topics)}")
    followup_task = _looks_like_followup_task(content)
    committed_change = _looks_like_committed_change(content)
    descriptive_structure = _looks_like_descriptive_structure(content)
    uncommitted_proposal = _looks_like_proposal(content) and not committed_change
    goal_statement = _looks_like_goal_statement(content)
    unit_quality_warnings = _source_unit_quality_warnings(candidate)

    weighted_cap = (
        0.28
        + 0.28 * model_score
        + 0.12 * confidence
        + 0.20 * support_score
    )
    if durable_marker and obj_type in {"decision", "method_change", "argument"}:
        weighted_cap += 0.03
    if (
        obj_type in {"decision", "method_change"}
        and durable_marker
        and committed_change
        and confidence >= 0.85
        and support_score >= 0.75
        and evidence_line_count >= 3
    ):
        weighted_cap += 0.05
    if obj_type == "todo":
        weighted_cap -= 0.04
    elif obj_type == "result":
        weighted_cap -= 0.06
    elif obj_type == "argument":
        weighted_cap -= 0.04
    elif obj_type == "open_question":
        weighted_cap -= 0.05
    score = min(score, weighted_cap)

    if token_count <= 3:
        score = min(score, 0.30)
    if support_score < 0.25:
        score = min(score, 0.72 if obj_type in {"todo", "result"} else 0.78)
    if confidence < 0.65:
        score = min(score, 0.72)
    if 0.25 <= support_score < 0.35:
        score = min(score, 0.80)
    if evidence_line_count <= 1:
        if obj_type == "result":
            score = min(score, 0.62)
        elif obj_type == "todo":
            score = min(score, 0.70)
        else:
            score = min(score, 0.78)
    if obj_type == "result" and not durable_marker:
        score = min(score, 0.72)
    if obj_type == "todo":
        score = min(score, 0.82)
    elif obj_type == "result" and support_score < 0.70:
        score = min(score, 0.80)
    elif obj_type == "argument":
        score = min(score, 0.78)
    elif obj_type == "open_question":
        score = min(score, 0.80)
    if obj_type in {"decision", "method_change"} and followup_task and not committed_change:
        score = min(score, 0.72)
    if descriptive_structure and obj_type == "result":
        score = min(score, 0.80)
    if uncommitted_proposal:
        score = min(score, 0.78)
    if goal_statement:
        score = min(score, 0.78)
    if "validator_repaired_source_unit" in unit_quality_warnings:
        score = min(score - 0.02, 0.84 if obj_type in {"decision", "method_change"} else 0.78)
    if "uncertain_source_unit" in unit_quality_warnings:
        score = min(score - 0.03, 0.82)
    if "source_unit_uncertainty_note" in unit_quality_warnings:
        score = min(score - 0.02, 0.82)

    return round(clamp_float(score), 2)


def _line_overlap(left: Any, right: Any) -> bool:
    if not isinstance(left, list) or not isinstance(right, list):
        return False
    return bool(set(left) & set(right))


def _line_overlap_score(left: Any, right: Any) -> float:
    if not isinstance(left, list) or not isinstance(right, list):
        return 0.0
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _line_gap(left: Any, right: Any) -> int | None:
    if not isinstance(left, list) or not isinstance(right, list):
        return None
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return None
    if left_set & right_set:
        return 0
    if max(left_set) < min(right_set):
        return min(right_set) - max(left_set) - 1
    return min(left_set) - max(right_set) - 1


def _duplicate_index(rows: list[dict[str, Any]], candidate: dict[str, Any]) -> int | None:
    content = str(candidate.get("content", ""))
    obj_type = str(candidate.get("type", ""))
    evidence_lines = candidate.get("evidence_lines", [])
    candidate_keys = set(candidate.get("_concept_keys", [])) or _concept_keys(candidate)
    best_match: tuple[float, int] | None = None

    def consider(index: int, priority: float) -> None:
        nonlocal best_match
        if best_match is None or priority > best_match[0]:
            best_match = (priority, index)

    for index, row in enumerate(rows):
        row_type = str(row.get("type", ""))
        similarity = jaccard(str(row.get("content", "")), content)
        overlap_score = _line_overlap_score(row.get("_evidence_lines", []), evidence_lines)
        gap = _line_gap(row.get("_evidence_lines", []), evidence_lines)
        shared_keys = set(row.get("_concept_keys", [])) & candidate_keys
        same_or_colliding_type = (
            row_type == obj_type
            or frozenset({row_type, obj_type})
            in {
                frozenset({"decision", "method_change"}),
                frozenset({"decision", "result"}),
                frozenset({"result", "method_change"}),
            }
        )
        if row_type == obj_type and similarity >= 0.52:
            consider(index, 100.0 + similarity + overlap_score)
        if row_type == obj_type and overlap_score >= 0.80:
            consider(index, 95.0 + overlap_score + similarity)
        if (
            frozenset({row_type, obj_type}) == frozenset({"todo", "open_question"})
            and (
                similarity >= 0.35
                or overlap_score >= 0.50
                or (shared_keys and gap is not None and gap <= 10)
            )
        ):
            consider(index, 90.0 + similarity + overlap_score)
        if (
            frozenset({row_type, obj_type}) == frozenset({"decision", "method_change"})
            and overlap_score >= 0.85
        ):
            consider(index, 85.0 + overlap_score + similarity)
        if shared_keys and same_or_colliding_type:
            if overlap_score >= 0.25:
                consider(index, 80.0 + overlap_score + similarity)
            if gap is not None and gap <= 20 and row_type == obj_type:
                consider(index, 75.0 + similarity - (gap / 100.0))
            if gap is not None and gap <= 4 and frozenset({row_type, obj_type}) in {
                frozenset({"decision", "method_change"}),
                frozenset({"decision", "result"}),
                frozenset({"result", "method_change"}),
            }:
                consider(index, 70.0 + similarity - (gap / 100.0))
            if (
                gap is not None
                and gap <= 12
                and frozenset({row_type, obj_type}) == frozenset({"decision", "method_change"})
            ):
                consider(index, 65.0 + similarity - (gap / 100.0))
        if (
            same_or_colliding_type
            and _line_overlap(row.get("_evidence_lines", []), evidence_lines)
            and similarity >= 0.28
        ):
            consider(index, 60.0 + similarity + overlap_score)
    return best_match[1] if best_match is not None else None


def _row_rank(row: dict[str, Any]) -> tuple[int, float, int, int]:
    return (
        TYPE_PRIORITY.get(str(row.get("type", "")), 0),
        clamp_float(row.get("importance", 0.0), fallback=0.0),
        len(row.get("_evidence_lines", [])),
        len(tokenize(str(row.get("content", "")))),
    )


def _merge_memory_rows(preferred: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    merged = dict(preferred)
    merged["importance"] = max(
        clamp_float(preferred.get("importance", 0.0), fallback=0.0),
        clamp_float(other.get("importance", 0.0), fallback=0.0),
    )
    merged["related_topics"] = unique_strings(
        list(preferred.get("related_topics", [])) + list(other.get("related_topics", []))
    )
    merged["_source_candidate_ids"] = unique_strings(
        list(preferred.get("_source_candidate_ids", []))
        + list(other.get("_source_candidate_ids", []))
    )
    merged["_evidence_lines"] = sorted(
        set(preferred.get("_evidence_lines", [])) | set(other.get("_evidence_lines", []))
    )
    merged["_concept_keys"] = sorted(
        set(preferred.get("_concept_keys", [])) | set(other.get("_concept_keys", []))
    )
    merged["_viewpoint_keys"] = sorted(
        set(preferred.get("_viewpoint_keys", [])) | set(other.get("_viewpoint_keys", []))
    )
    merged["_unit_quality_warnings"] = sorted(
        set(preferred.get("_unit_quality_warnings", []))
        | set(other.get("_unit_quality_warnings", []))
    )
    if "read_write_memory_update" in merged["_concept_keys"]:
        preferred_has_functions = _has_any(
            str(preferred.get("content", "")),
            ("read", "`read`", "write", "`write`"),
        )
        other_has_functions = _has_any(
            str(other.get("content", "")),
            ("read", "`read`", "write", "`write`"),
        )
        if other_has_functions and not preferred_has_functions:
            merged["content"] = other.get("content", "")
    if len(str(other.get("evidence", ""))) > len(str(preferred.get("evidence", ""))):
        merged["evidence"] = other.get("evidence", "")
    return merged


def _count_line_episodes(
    line_ids: list[int],
    *,
    gap_lines: int = VIEWPOINT_EPISODE_GAP_LINES,
) -> int:
    unique_lines = sorted(set(int(line_id) for line_id in line_ids))
    if not unique_lines:
        return 0
    episodes = 1
    previous = unique_lines[0]
    for line_id in unique_lines[1:]:
        if line_id - previous > gap_lines:
            episodes += 1
        previous = line_id
    return episodes


def _line_ranges(line_ids: list[int]) -> list[dict[str, int]]:
    unique_lines = sorted(set(int(line_id) for line_id in line_ids))
    if not unique_lines:
        return []
    ranges: list[dict[str, int]] = []
    start = previous = unique_lines[0]
    for line_id in unique_lines[1:]:
        if line_id == previous + 1:
            previous = line_id
            continue
        ranges.append({"start_line": start, "end_line": previous})
        start = previous = line_id
    ranges.append({"start_line": start, "end_line": previous})
    return ranges


def _viewpoint_bonus(episode_count: int) -> float:
    if episode_count <= 1:
        return 0.0
    bounded = min(max(episode_count, 2), max(VIEWPOINT_RECURRENCE_BONUS_BY_EPISODES))
    return VIEWPOINT_RECURRENCE_BONUS_BY_EPISODES[bounded]


def _apply_viewpoint_recurrence(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply a small bounded bonus when a concept returns in separated episodes."""
    grouped: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        line_ids = [
            int(line_id)
            for line_id in row.get("_evidence_lines", [])
            if isinstance(line_id, int) or str(line_id).isdigit()
        ]
        for viewpoint_key in row.get("_viewpoint_keys", []):
            key = str(viewpoint_key or "").strip()
            if not key:
                continue
            item = grouped.setdefault(
                key,
                {
                    "viewpoint_key": key,
                    "row_indexes": [],
                    "source_candidate_ids": [],
                    "evidence_lines": [],
                },
            )
            item["row_indexes"].append(index)
            item["evidence_lines"].extend(line_ids)
            item["source_candidate_ids"].extend(row.get("_source_candidate_ids", []))

    recurrence_by_key: dict[str, dict[str, Any]] = {}
    for key, item in grouped.items():
        line_ids = sorted(set(item["evidence_lines"]))
        episode_count = _count_line_episodes(line_ids)
        bonus = _viewpoint_bonus(episode_count)
        recurrence_by_key[key] = {
            "viewpoint_key": key,
            "episode_count": episode_count,
            "bonus": bonus,
            "object_count": len(set(item["row_indexes"])),
            "evidence_line_ranges": _line_ranges(line_ids),
            "source_candidate_ids": unique_strings(item["source_candidate_ids"]),
            "applied_object_count": 0,
            "affected_objects": [],
            "capped_objects": [],
            "superseded_by_stronger_viewpoint_count": 0,
        }

    adjusted_rows: list[dict[str, Any]] = []
    for row in rows:
        applicable = [
            recurrence_by_key[key]
            for key in row.get("_viewpoint_keys", [])
            if key in recurrence_by_key and recurrence_by_key[key]["bonus"] > 0
        ]
        if not applicable:
            adjusted_rows.append(row)
            continue
        strongest = max(
            applicable,
            key=lambda item: (item["bonus"], item["episode_count"], item["viewpoint_key"]),
        )
        for item in applicable:
            if item is not strongest:
                item["superseded_by_stronger_viewpoint_count"] += 1
        adjusted = dict(row)
        base_importance = clamp_float(row.get("importance", 0.0), fallback=0.0)
        type_cap = VIEWPOINT_RECURRENCE_TYPE_CAPS.get(str(row.get("type", "")), 0.96)
        adjusted_importance = min(type_cap, base_importance + strongest["bonus"])
        adjusted["importance"] = round(clamp_float(adjusted_importance), 2)
        actual_bonus = round(adjusted["importance"] - round(base_importance, 2), 2)
        if actual_bonus > 0:
            adjusted["_viewpoint_recurrence"] = {
                "viewpoint_key": strongest["viewpoint_key"],
                "episode_count": strongest["episode_count"],
                "configured_bonus": round(strongest["bonus"], 2),
                "actual_bonus": actual_bonus,
                "base_importance": round(base_importance, 2),
                "adjusted_importance": adjusted["importance"],
            }
            strongest["applied_object_count"] += 1
            strongest["affected_objects"].append(
                {
                    "type": str(row.get("type", "")),
                    "content": str(row.get("content", "")),
                    "base_importance": round(base_importance, 2),
                    "adjusted_importance": adjusted["importance"],
                    "actual_bonus": actual_bonus,
                }
            )
        else:
            strongest["capped_objects"].append(
                {
                    "type": str(row.get("type", "")),
                    "content": str(row.get("content", "")),
                    "base_importance": round(base_importance, 2),
                    "type_cap": type_cap,
                    "reason": "importance_already_at_type_cap",
                }
            )
        adjusted_rows.append(adjusted)

    report = sorted(
        [
            item
            for item in recurrence_by_key.values()
            if item["episode_count"] > 1
        ],
        key=lambda item: (-item["episode_count"], item["viewpoint_key"]),
    )
    return adjusted_rows, report


def resolve_cross_type_conflicts(
    grounded_candidates: list[GroundedCandidate | dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[ConflictDecision]]:
    pending = [_as_candidate_dict(candidate) for candidate in grounded_candidates]
    kept: list[dict[str, Any]] = []
    decisions: list[ConflictDecision] = []
    dropped_ids: set[str] = set()

    collision_pairs = {
        frozenset({"decision", "method_change"}),
        frozenset({"decision", "result"}),
        frozenset({"result", "method_change"}),
    }

    for index, candidate in enumerate(pending):
        candidate_id = str(candidate.get("candidate_id", ""))
        if candidate_id in dropped_ids:
            continue
        merged = dict(candidate)
        for other in pending[index + 1 :]:
            other_id = str(other.get("candidate_id", ""))
            if other_id in dropped_ids:
                continue
            type_pair = frozenset({str(merged.get("type", "")), str(other.get("type", ""))})
            if type_pair not in collision_pairs:
                continue
            similarity = jaccard(merged.get("content", ""), other.get("content", ""))
            if not _same_span(merged, other):
                continue
            if similarity >= 0.78:
                merged = _merge_candidate(merged, other)
                dropped_ids.add(other_id)
                decisions.append(
                    ConflictDecision(
                        decision_id=f"R-{len(decisions) + 1:03d}",
                        action="merge",
                        candidate_ids=[candidate_id, other_id],
                        output_candidate_id=str(merged.get("candidate_id", "")),
                        reason=(
                            "overlapping evidence and high text similarity; "
                            "preferred operational type before verification"
                        ),
                        rewritten_candidate=merged,
                    )
                )
            else:
                decisions.append(
                    ConflictDecision(
                        decision_id=f"R-{len(decisions) + 1:03d}",
                        action="keep",
                        candidate_ids=[str(merged.get("candidate_id", "")), other_id],
                        output_candidate_id=str(merged.get("candidate_id", "")),
                        reason=(
                            "same evidence span is allowed because candidates answer "
                            "different semantic questions"
                        ),
                    )
                )
        kept.append(merged)

    for candidate in kept:
        decisions.append(
            ConflictDecision(
                decision_id=f"R-{len(decisions) + 1:03d}",
                action="keep",
                candidate_ids=[str(candidate.get("candidate_id", ""))],
                output_candidate_id=str(candidate.get("candidate_id", "")),
                reason="candidate survived cross-type conflict review",
            )
        )
    return kept, decisions


def reduce_l1_patch(
    verified_candidates: list[dict[str, Any]],
    *,
    meeting_id: str,
    start_seq: int = 1,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for candidate in verified_candidates:
        obj_type = str(candidate.get("type", "")).strip()
        content = str(candidate.get("content", "")).strip()
        evidence = str(candidate.get("evidence_quote", "")).strip()
        obj_type = _normalize_candidate_type(obj_type, content=content, evidence=evidence)
        related_topics = unique_strings(candidate.get("related_topics", []))
        importance = _multi_agent_importance(
            candidate,
            obj_type=obj_type,
            content=content,
            evidence=evidence,
            related_topics=related_topics,
        )
        if not content or importance < MIN_IMPORTANCE_THRESHOLD:
            continue
        row = {
            "type": obj_type,
            "content": content,
            "importance": importance,
            "evidence": evidence,
            "related_topics": related_topics,
            "related_obj_ids": [],
            "_evidence_lines": list(candidate.get("evidence_lines", [])),
            "_source_candidate_ids": [str(candidate.get("candidate_id", ""))],
            "_concept_keys": sorted(
                _concept_keys(
                    {
                        **candidate,
                        "type": obj_type,
                        "content": content,
                        "related_topics": related_topics,
                    }
                )
            ),
            "_viewpoint_keys": sorted(
                _viewpoint_keys(
                    {
                        **candidate,
                        "type": obj_type,
                        "content": content,
                        "related_topics": related_topics,
                    }
                )
            ),
            "_unit_quality_warnings": sorted(_source_unit_quality_warnings(candidate)),
        }
        duplicate_at = _duplicate_index(rows, {**candidate, **row})
        if duplicate_at is None:
            rows.append(row)
            continue
        existing = rows[duplicate_at]
        preferred, other = (
            (row, existing)
            if _row_rank(row) > _row_rank(existing)
            else (existing, row)
        )
        rows[duplicate_at] = _merge_memory_rows(preferred, other)

    rows, viewpoint_recurrence = _apply_viewpoint_recurrence(rows)

    memory_objects: list[dict[str, Any]] = []
    seq = start_seq
    for row in rows:
        memory_objects.append(
            {
                "obj_id": f"L1-{meeting_id}-{seq:03d}",
                "type": row["type"],
                "content": row["content"],
                "importance": row["importance"],
                "evidence": row["evidence"],
                "related_topics": row["related_topics"],
                "related_obj_ids": [],
            }
        )
        seq += 1

    patch = {
        "meeting_id": meeting_id,
        "operation": "replace_meeting_l1",
        "memory_objects": memory_objects,
        "source_candidate_ids": [
            str(candidate.get("candidate_id", "")) for candidate in verified_candidates
        ],
        "viewpoint_recurrence": viewpoint_recurrence,
    }
    return patch, memory_objects
