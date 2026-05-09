from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]", re.IGNORECASE)

SEMANTIC_ANCHOR_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "idea_unit",
        (
            "idea unit",
            "idea units",
            "想法單元",
            "想法單位",
        ),
    ),
    (
        "taxonomy_labeling",
        (
            "type agent",
            "type agents",
            "typed agent",
            "classified",
            "classification",
            "tagged",
            "predefined label",
            "predefined labels",
            "type label",
            "type labels",
            "final label",
            "final labels",
            "labeling process",
            "labeling",
            "predefined tag",
            "predefined tags",
            "taxonomy",
            "標籤",
            "分類",
            "類型",
            "預定義",
        ),
    ),
    (
        "six_role_set",
        (
            "six type",
            "six types",
            "six predefined",
            "六個",
            "六種",
        ),
    ),
    ("decision_role", ("decision", "決策")),
    ("todo_role", ("to-do", "todo", "action item", "action_item", "待辦", "待辦事項")),
    ("method_change_role", ("method change", "approach change", "方法變更")),
    ("result_role", ("result", "finding", "結果")),
    ("argument_role", ("argument", "論點", "論證")),
    ("open_question_role", ("open question", "open issue", "開放問題", "未解決")),
    (
        "memory_update",
        (
            "memory update",
            "update memory",
            "memory structure",
            "記憶體更新",
            "記憶更新",
            "記憶結構",
        ),
    ),
    (
        "memory_retention_decay",
        (
            "retention",
            "activation",
            "static importance",
            "dynamic activation",
            "recency",
            "decay",
            "delete",
            "deleted",
            "not discussed",
            "three meetings",
            "meeting id",
            "meeting ids",
            "保留",
            "時效",
            "衰減",
            "刪除",
            "未被討論",
            "三次會議",
            "會議 id",
        ),
    ),
    (
        "dataset_sourcing",
        (
            "dataset",
            "data sourcing",
            "research paper",
            "published paper",
            "paper",
            "資料集",
            "數據集",
            "論文",
            "替代方案",
            "完整",
            "零碎",
        ),
    ),
    (
        "memo_rag_evaluation",
        (
            "memo",
            "rag",
            "multi-hop",
            "multi hop",
            "token consumption",
            "latency",
            "baseline",
            "locomo",
            "低 token",
            "延遲",
            "多跳",
        ),
    ),
    (
        "unanswerable_question_evaluation",
        (
            "unanswerable",
            "cannot answer",
            "unable to answer",
            "unanswerable question",
            "unanswerable questions",
            "無法回答",
        ),
    ),
    (
        "llm_as_judge_evaluation",
        (
            "llm-as-judge",
            "llm as judge",
            "llm judge",
            "judge",
            "binary correct/incorrect",
            "correct/incorrect",
            "correct or incorrect",
            "semantic similarity",
            "factually incorrect",
            "對或錯",
            "評審",
        ),
    ),
    (
        "precision_recall_chunking_evaluation",
        (
            "precision",
            "recall",
            "precision/recall",
            "human-annotated",
            "human annotated",
            "important idea units",
            "ground truth",
            "chunking evaluation",
        ),
    ),
    (
        "forgetting_mechanism",
        (
            "forgetting mechanism",
            "memory forgetting",
            "external database",
            "delete data",
            "deleting data",
            "model weights",
            "altering the llm",
            "遺忘",
            "資料庫",
            "權重",
            "刪掉",
            "踢掉",
        ),
    ),
    (
        "adaptive_segmentation_tradeoff",
        (
            "adaptive segmentation",
            "adaptive window",
            "dynamic window",
            "boundary adjustment",
            "boundary adjustments",
            "boundary repair",
            "larger chunks",
            "large chunks",
            "downstream llm",
            "fixed chunk",
            "adaptive segmentation methods",
            "自適應",
            "分段",
            "文本塊",
            "動態",
            "邊界",
        ),
    ),
    (
        "dynamic_chunking_evaluation",
        (
            "dynamic chunking",
            "fixed-size",
            "fixed size",
            "sentence-by-sentence",
            "sentence level",
            "function call",
            "function calls",
            "processing time",
            "runtime",
        ),
    ),
    (
        "memory_processing_architecture",
        (
            "top-down",
            "bottom-up",
            "processing architecture",
            "segment-first",
            "idea unit merging",
            "hierarchical memory processing",
            "memory hierarchy",
            "由上而下",
            "由下而上",
        ),
    ),
    (
        "memory_architecture_rules",
        (
            "memory architecture",
            "update rules",
            "short-term",
            "long-term",
            "relationship",
            "relationship between",
        ),
    ),
    (
        "single_pass_global_vector",
        (
            "single-pass",
            "single pass",
            "global vector",
            "post-hoc",
            "post hoc",
            "initial nodes",
        ),
    ),
    (
        "candidate_object_merge",
        (
            "create_object",
            "candidate object",
            "candidate objects",
            "candidate",
            "candidate memory integration",
            "subsequent text",
            "later content",
            "merged when connected",
            "merges related",
            "merges later relevant",
        ),
    ),
    (
        "agent_orchestration_state",
        (
            "function calling",
            "function call",
            "external code",
            "external programmatic control",
            "programmatic control",
            "processing state",
            "sentences have been processed",
            "which sentences have been processed",
            "which lines have been processed",
            "boolean flag",
            "next starting line",
            "prevent overlaps",
            "internal program state",
            "incrementing a counter",
            "local function",
            "manager agent",
            "llm-orchestrated",
            "execution model",
            "intermediate checkpoints",
            "intermediate steps",
            "logging/replay",
            "inspectable",
            "control and inspection",
            "函數呼叫",
            "函式呼叫",
            "管理者代理",
        ),
    ),
    (
        "code_driven_llm_control",
        (
            "code-driven",
            "code driven",
            "primary controller",
            "code remains",
            "host application maintains control",
            "main code-driven",
            "control flow",
            "llm-controlled",
            "llm controlled",
            "specific judgment",
            "specific judgement",
            "delegated judgment",
            "delegated judgement",
            "returned value",
            "determine the next action",
            "next action",
        ),
    ),
    (
        "api_access_budget",
        (
            "gemini api",
            "api usage fees",
            "api access",
            "direct payment",
            "direct budget",
            "credit",
            "credits",
            "nt$9000",
            "nt$20,000",
            "9000 credit",
            "20,000 budget",
            "vertex ai",
            "policy change",
            "payment method",
        ),
    ),
    (
        "real_time_demo",
        (
            "real-time",
            "real time",
            "demo",
            "demonstration",
            "demo flow",
        ),
    ),
    (
        "agent_modularity",
        (
            "modularity",
            "specialized agent",
            "swapped",
            "fixed and dynamic",
            "line-jumping agent",
            "manager/agent",
            "manager agent",
            "manager lean",
            "manager component",
            "overloaded",
            "dispatcher",
            "delegating",
            "delegates",
            "worker agent",
            "worker agents",
            "fine-grained tasks",
            "detailed tasks",
            "specialized agents",
            "different implementations",
            "模組",
        ),
    ),
    (
        "separation_of_concerns",
        (
            "separation of concerns",
            "not pure delegator",
            "pure delegator",
            "how many lines",
            "manager decides",
        ),
    ),
    (
        "multi_agent_debugging",
        (
            "multi-agent",
            "multi agent",
            "debugging",
            "unit testing",
            "monolithic",
        ),
    ),
    (
        "data_fragmentation_prevention",
        (
            "data fragmentation",
            "prevent data fragmentation",
            "irrelevant co-located",
            "co-located",
            "not bundled",
            "idea units",
        ),
    ),
    (
        "memory_node_convergence",
        (
            "node convergence",
            "memory nodes",
            "large text chunk",
            "large text segment",
            "large text segments",
            "update parameters",
            "cross-pollinated",
            "information bleeding",
            "redundant",
            "節點收斂",
            "冗餘",
        ),
    ),
    (
        "l123_hierarchy",
        (
            "three-level",
            "three level",
            "l1",
            "l2",
            "l3",
            "hierarchy",
            "三層",
            "層級",
            "最高級",
        ),
    ),
    (
        "meeting_scoped_merge",
        (
            "same meeting",
            "single meeting",
            "cross-meeting",
            "cross meeting",
            "not merged across",
            "merge only",
            "同一次會議",
            "單次會議",
            "不會跨會議",
            "跨會議",
            "合併",
        ),
    ),
    ("topic_tree", ("topic-tree", "topic tree", "topic node", "主題樹", "主題節點")),
    ("retrieval", ("retrieval", "recall", "檢索", "召回")),
)

SPECIFIC_SEMANTIC_ANCHORS = {
    "taxonomy_labeling",
    "six_role_set",
    "memory_update",
    "memory_retention_decay",
    "dataset_sourcing",
    "memo_rag_evaluation",
    "unanswerable_question_evaluation",
    "llm_as_judge_evaluation",
    "precision_recall_chunking_evaluation",
    "forgetting_mechanism",
    "adaptive_segmentation_tradeoff",
    "dynamic_chunking_evaluation",
    "memory_processing_architecture",
    "memory_architecture_rules",
    "single_pass_global_vector",
    "candidate_object_merge",
    "agent_orchestration_state",
    "code_driven_llm_control",
    "api_access_budget",
    "real_time_demo",
    "agent_modularity",
    "separation_of_concerns",
    "multi_agent_debugging",
    "data_fragmentation_prevention",
    "memory_node_convergence",
    "l123_hierarchy",
    "meeting_scoped_merge",
    "topic_tree",
    "retrieval",
}

EVIDENCE_DOMINANT_SEMANTIC_ANCHORS = {
    "memory_retention_decay",
    "memo_rag_evaluation",
    "unanswerable_question_evaluation",
    "precision_recall_chunking_evaluation",
    "forgetting_mechanism",
}

TRANSLATION_EVIDENCE_SEMANTIC_ANCHORS = {
    "agent_modularity",
    "taxonomy_labeling",
    "six_role_set",
}

WATCHLIST_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "locomo_multi_hop_definition",
        (
            "locomo",
            "multi-hop",
        ),
    ),
    (
        "batch_definition_unresolved",
        (
            "batch",
            "definition",
        ),
    ),
    (
        "l1_discard_importance_implementation",
        (
            "l1",
            "discard",
            "importance",
        ),
    ),
)


def load_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _tokens(value: Any) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(str(value or ""))}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _anchor_marker_matches(text: str, marker: str) -> bool:
    marker = marker.lower().strip()
    if not marker:
        return False
    if re.fullmatch(r"[a-z0-9_][a-z0-9_\-\s]*[a-z0-9_]", marker):
        return re.search(rf"(?<![a-z0-9_]){re.escape(marker)}(?![a-z0-9_])", text) is not None
    return marker in text


def _anchor_similarity(baseline: set[str], candidate: set[str]) -> float:
    if not baseline or not candidate:
        return 0.0
    jaccard = _jaccard(baseline, candidate)
    baseline_coverage = len(baseline & candidate) / len(baseline)
    return max(jaccard, baseline_coverage)


def _semantic_anchor_set(obj: dict[str, Any]) -> set[str]:
    raw_topics = obj.get("related_topics", [])
    topics = " ".join(str(topic) for topic in raw_topics) if isinstance(raw_topics, list) else ""
    text = " ".join(
        [
            str(obj.get("content", "") or ""),
            str(obj.get("evidence", "") or ""),
            topics,
        ]
    ).lower()
    anchors: set[str] = set()
    for name, markers in SEMANTIC_ANCHOR_GROUPS:
        if any(_anchor_marker_matches(text, marker) for marker in markers):
            anchors.add(name)
    return anchors


def _watchlist_text(obj: dict[str, Any]) -> str:
    raw_topics = obj.get("related_topics", [])
    topics = " ".join(str(topic) for topic in raw_topics) if isinstance(raw_topics, list) else ""
    return " ".join(
        [
            str(obj.get("content", "") or ""),
            str(obj.get("evidence", "") or ""),
            topics,
        ]
    ).lower()


def _watchlist_code(obj: dict[str, Any]) -> str | None:
    text = _watchlist_text(obj)
    for code, required_markers in WATCHLIST_MARKERS:
        if all(_anchor_marker_matches(text, marker) for marker in required_markers):
            return code
    return None


def _topic_set(obj: dict[str, Any]) -> set[str]:
    return {
        str(topic).strip().lower()
        for topic in obj.get("related_topics", [])
        if str(topic).strip()
    }


def iter_l1_objects(tree: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for meeting in tree.get("meetings", []):
        meeting_id = str(meeting.get("meeting_id", ""))
        for index, obj in enumerate(meeting.get("memory_objects", []), start=1):
            row = dict(obj)
            row.setdefault("obj_id", f"{meeting_id}:{index:03d}")
            row["meeting_id"] = str(obj.get("meeting_id") or meeting_id)
            row["_content_tokens"] = _tokens(row.get("content", ""))
            row["_evidence_tokens"] = _tokens(row.get("evidence", ""))
            row["_topic_set"] = _topic_set(row)
            row["_semantic_anchors"] = _semantic_anchor_set(row)
            rows.append(row)
    return rows


def _match_score(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, float]:
    baseline_anchors = baseline.get("_semantic_anchors", set())
    candidate_anchors = candidate.get("_semantic_anchors", set())
    evidence_similarity = _jaccard(
        baseline.get("_evidence_tokens", set()),
        candidate.get("_evidence_tokens", set()),
    )
    content_similarity = _jaccard(
        baseline.get("_content_tokens", set()),
        candidate.get("_content_tokens", set()),
    )
    topic_similarity = _jaccard(
        baseline.get("_topic_set", set()),
        candidate.get("_topic_set", set()),
    )
    semantic_anchor_similarity = _anchor_similarity(
        baseline_anchors,
        candidate_anchors,
    )
    specific_anchor_overlap = 1.0 if baseline_anchors & candidate_anchors & SPECIFIC_SEMANTIC_ANCHORS else 0.0
    evidence_dominant_anchor_overlap = (
        1.0 if baseline_anchors & candidate_anchors & EVIDENCE_DOMINANT_SEMANTIC_ANCHORS else 0.0
    )
    translation_evidence_anchor_overlap = (
        1.0 if baseline_anchors & candidate_anchors & TRANSLATION_EVIDENCE_SEMANTIC_ANCHORS else 0.0
    )
    same_meeting_bonus = 1.0 if baseline.get("meeting_id") == candidate.get("meeting_id") else 0.0
    score = (
        0.45 * evidence_similarity
        + 0.35 * content_similarity
        + 0.15 * topic_similarity
        + 0.05 * same_meeting_bonus
    )
    semantic_score = min(1.0, score + 0.32 * semantic_anchor_similarity + 0.18 * specific_anchor_overlap)
    return {
        "score": round(score, 4),
        "semantic_score": round(semantic_score, 4),
        "evidence_similarity": round(evidence_similarity, 4),
        "content_similarity": round(content_similarity, 4),
        "topic_similarity": round(topic_similarity, 4),
        "semantic_anchor_similarity": round(semantic_anchor_similarity, 4),
        "specific_anchor_overlap": specific_anchor_overlap,
        "evidence_dominant_anchor_overlap": evidence_dominant_anchor_overlap,
        "translation_evidence_anchor_overlap": translation_evidence_anchor_overlap,
        "same_meeting_bonus": same_meeting_bonus,
    }


def _clean_obj(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in obj.items()
        if not str(key).startswith("_")
    }


def _best_match(
    baseline_obj: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    threshold: float,
) -> tuple[dict[str, Any] | None, dict[str, float], dict[str, Any] | None]:
    best_candidate: dict[str, Any] | None = None
    best_score: dict[str, float] = {"score": 0.0, "semantic_score": 0.0}
    best_accepted_candidate: dict[str, Any] | None = None
    best_accepted_score: dict[str, float] = {"score": 0.0, "semantic_score": 0.0}
    for candidate in candidates:
        score = _match_score(baseline_obj, candidate)
        if score["semantic_score"] > best_score.get("semantic_score", 0.0):
            best_candidate = candidate
            best_score = score
        if _accepted_match(score, threshold=threshold) and score["semantic_score"] > best_accepted_score.get(
            "semantic_score",
            0.0,
        ):
            best_accepted_candidate = candidate
            best_accepted_score = score
    if best_candidate is None:
        return None, best_score, None
    if best_accepted_candidate is not None:
        return best_accepted_candidate, best_accepted_score, best_accepted_candidate
    return None, best_score, best_candidate


def _accepted_match(score: dict[str, float], *, threshold: float) -> bool:
    return (
        score.get("score", 0.0) >= threshold
        or score.get("evidence_similarity", 0.0) >= 0.65
        or _strong_semantic_coverage(score)
    )


def _strong_semantic_coverage(score: dict[str, float]) -> bool:
    return (
        score.get("same_meeting_bonus", 0.0) >= 1.0
        and (
            (
                score.get("semantic_anchor_similarity", 0.0) >= 0.45
                and (
                    (
                        score.get("evidence_similarity", 0.0) >= 0.28
                        and (
                            (
                                score.get("semantic_score", 0.0) >= 0.50
                                and (
                                    score.get("content_similarity", 0.0) >= 0.10
                                    or score.get("topic_similarity", 0.0) >= 0.05
                                    or score.get("evidence_similarity", 0.0) >= 0.65
                                )
                            )
                            or (
                                score.get("semantic_score", 0.0) >= 0.45
                                and score.get("content_similarity", 0.0) >= 0.35
                            )
                            or (
                                score.get("specific_anchor_overlap", 0.0) >= 1.0
                                and score.get("evidence_dominant_anchor_overlap", 0.0) >= 1.0
                                and score.get("evidence_similarity", 0.0) >= 0.55
                                and score.get("semantic_score", 0.0) >= 0.45
                            )
                        )
                    )
                    or (
                        score.get("specific_anchor_overlap", 0.0) >= 1.0
                        and score.get("semantic_anchor_similarity", 0.0) >= 0.75
                        and score.get("semantic_score", 0.0) >= 0.40
                        and (
                            score.get("topic_similarity", 0.0) >= 0.10
                            or score.get("content_similarity", 0.0) >= 0.10
                            or (
                                score.get("evidence_similarity", 0.0) >= 0.20
                                and (
                                    score.get("content_similarity", 0.0) >= 0.10
                                    or score.get("topic_similarity", 0.0) >= 0.05
                                )
                            )
                        )
                    )
                    or (
                        score.get("specific_anchor_overlap", 0.0) >= 1.0
                        and score.get("semantic_anchor_similarity", 0.0) >= 0.50
                        and score.get("evidence_similarity", 0.0) >= 0.28
                        and score.get("semantic_score", 0.0) >= 0.35
                        and (
                            score.get("topic_similarity", 0.0) >= 0.05
                            or score.get("content_similarity", 0.0) >= 0.10
                            or (
                                score.get("evidence_similarity", 0.0) >= 0.38
                                and (
                                    score.get("content_similarity", 0.0) >= 0.10
                                    or score.get("topic_similarity", 0.0) >= 0.05
                                )
                            )
                        )
                    )
                )
            )
            or (
                score.get("specific_anchor_overlap", 0.0) >= 1.0
                and score.get("semantic_anchor_similarity", 0.0) >= 0.30
                and score.get("evidence_similarity", 0.0) >= 0.28
                and score.get("semantic_score", 0.0) >= 0.45
                and (
                    score.get("content_similarity", 0.0) >= 0.10
                    or (
                        score.get("evidence_similarity", 0.0) >= 0.38
                        and (
                            score.get("content_similarity", 0.0) >= 0.10
                            or score.get("topic_similarity", 0.0) >= 0.05
                        )
                    )
                )
            )
            or (
                score.get("specific_anchor_overlap", 0.0) >= 1.0
                and score.get("semantic_anchor_similarity", 0.0) >= 0.30
                and score.get("evidence_similarity", 0.0) >= 0.25
                and score.get("content_similarity", 0.0) >= 0.18
                and score.get("semantic_score", 0.0) >= 0.45
            )
            or (
                score.get("translation_evidence_anchor_overlap", 0.0) >= 1.0
                and score.get("semantic_anchor_similarity", 0.0) >= 0.30
                and score.get("evidence_similarity", 0.0) >= 0.28
                and score.get("semantic_score", 0.0) >= 0.45
            )
            or (
                score.get("evidence_dominant_anchor_overlap", 0.0) >= 1.0
                and score.get("semantic_anchor_similarity", 0.0) >= 0.30
                and score.get("evidence_similarity", 0.0) >= 0.28
                and score.get("topic_similarity", 0.0) >= 0.10
                and score.get("semantic_score", 0.0) >= 0.45
            )
            or (
                score.get("evidence_dominant_anchor_overlap", 0.0) >= 1.0
                and score.get("semantic_anchor_similarity", 0.0) >= 0.55
                and score.get("evidence_similarity", 0.0) >= 0.38
                and score.get("semantic_score", 0.0) >= 0.55
            )
        )
    )


def _possible_semantic_coverage(
    score: dict[str, float],
    best_candidate: dict[str, Any] | None,
) -> bool:
    if best_candidate is None:
        return False
    return _strong_semantic_coverage(score) or (
        score.get("same_meeting_bonus", 0.0) >= 1.0
        and score.get("evidence_similarity", 0.0) >= 0.30
        and score.get("content_similarity", 0.0) >= 0.30
    )


def _importance_delta_summary(matches: list[dict[str, Any]]) -> dict[str, Any]:
    signed_deltas: list[float] = []
    for match in matches:
        try:
            baseline_value = float(match.get("baseline_importance", 0.0) or 0.0)
            candidate_value = float(match.get("candidate_importance", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        signed_deltas.append(candidate_value - baseline_value)

    if not signed_deltas:
        return {
            "matched_count": 0,
            "mean_abs": 0.0,
            "median_abs": 0.0,
            "p90_abs": 0.0,
            "max_abs": 0.0,
            "signed_mean": 0.0,
        }

    abs_deltas = sorted(abs(delta) for delta in signed_deltas)
    midpoint = len(abs_deltas) // 2
    median_abs = (
        (abs_deltas[midpoint - 1] + abs_deltas[midpoint]) / 2
        if len(abs_deltas) % 2 == 0
        else abs_deltas[midpoint]
    )
    p90_index = min(len(abs_deltas) - 1, int(round((len(abs_deltas) - 1) * 0.90)))
    return {
        "matched_count": len(signed_deltas),
        "mean_abs": round(sum(abs_deltas) / len(abs_deltas), 4),
        "median_abs": round(median_abs, 4),
        "p90_abs": round(abs_deltas[p90_index], 4),
        "max_abs": round(max(abs_deltas), 4),
        "signed_mean": round(sum(signed_deltas) / len(signed_deltas), 4),
    }


def compare_l1_trees(
    baseline_tree: dict[str, Any],
    candidate_tree: dict[str, Any],
    *,
    high_importance_threshold: float = 0.70,
    match_threshold: float = 0.42,
) -> dict[str, Any]:
    baseline_objects = iter_l1_objects(baseline_tree)
    candidate_objects = iter_l1_objects(candidate_tree)
    candidates_by_meeting: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in candidate_objects:
        candidates_by_meeting[str(obj.get("meeting_id", ""))].append(obj)

    matches: list[dict[str, Any]] = []
    matched_candidate_ids: set[str] = set()
    unmatched_baseline: list[dict[str, Any]] = []
    manual_review_queue: list[dict[str, Any]] = []

    for baseline_obj in baseline_objects:
        meeting_id = str(baseline_obj.get("meeting_id", ""))
        scoped_candidates = candidates_by_meeting.get(meeting_id) or candidate_objects
        matched, score, best_candidate = _best_match(
            baseline_obj,
            scoped_candidates,
            threshold=match_threshold,
        )
        if matched is None:
            clean_baseline = _clean_obj(baseline_obj)
            watchlist_code = _watchlist_code(baseline_obj)
            unmatched_baseline.append(
                {
                    "baseline": clean_baseline,
                    "best_score": score,
                    "watchlist_code": watchlist_code,
                    "possible_semantic_coverage": _possible_semantic_coverage(
                        score,
                        best_candidate,
                    ),
                    "best_candidate": _clean_obj(best_candidate) if best_candidate else None,
                }
            )
            is_high_importance = (
                float(baseline_obj.get("importance", 0.0) or 0.0) >= high_importance_threshold
            )
            if is_high_importance or watchlist_code:
                manual_review_queue.append(
                    {
                        "reason": (
                            "high_importance_baseline_unmatched"
                            if is_high_importance
                            else "watchlist_baseline_unmatched"
                        ),
                        "watchlist_code": watchlist_code,
                        "baseline_obj_id": str(baseline_obj.get("obj_id", "")),
                        "meeting_id": meeting_id,
                        "type": str(baseline_obj.get("type", "")),
                        "importance": baseline_obj.get("importance", 0.0),
                        "content": baseline_obj.get("content", ""),
                        "evidence": baseline_obj.get("evidence", ""),
                        "related_topics": baseline_obj.get("related_topics", []),
                        "best_score": score,
                        "possible_semantic_coverage": _possible_semantic_coverage(
                            score,
                            best_candidate,
                        ),
                        "best_candidate": _clean_obj(best_candidate) if best_candidate else None,
                    }
                )
            continue

        matched_candidate_ids.add(str(matched.get("obj_id", "")))
        matches.append(
            {
                "baseline_obj_id": str(baseline_obj.get("obj_id", "")),
                "candidate_obj_id": str(matched.get("obj_id", "")),
                "meeting_id": meeting_id,
                "score": score,
                "baseline_type": str(baseline_obj.get("type", "")),
                "candidate_type": str(matched.get("type", "")),
                "candidate_legacy_type": str(matched.get("legacy_type", "")),
                "baseline_importance": baseline_obj.get("importance", 0.0),
                "candidate_importance": matched.get("importance", 0.0),
            }
        )

    new_only = [
        _clean_obj(obj)
        for obj in candidate_objects
        if str(obj.get("obj_id", "")) not in matched_candidate_ids
    ]

    meeting_summaries = []
    meeting_ids = sorted(
        {
            str(obj.get("meeting_id", ""))
            for obj in [*baseline_objects, *candidate_objects]
            if str(obj.get("meeting_id", ""))
        }
    )
    for meeting_id in meeting_ids:
        baseline_count = sum(1 for obj in baseline_objects if obj.get("meeting_id") == meeting_id)
        candidate_count = sum(1 for obj in candidate_objects if obj.get("meeting_id") == meeting_id)
        matched_count = sum(1 for match in matches if match.get("meeting_id") == meeting_id)
        coverage_rate = matched_count / baseline_count if baseline_count else 1.0
        count_ratio = candidate_count / baseline_count if baseline_count else 1.0
        meeting_summaries.append(
            {
                "meeting_id": meeting_id,
                "baseline_count": baseline_count,
                "candidate_count": candidate_count,
                "matched_count": matched_count,
                "coverage_rate": round(coverage_rate, 4),
                "count_ratio": round(count_ratio, 4),
                "below_count_gate": baseline_count > 0 and count_ratio < 0.70,
            }
        )

    baseline_count = len(baseline_objects)
    candidate_count = len(candidate_objects)
    coverage_rate = len(matches) / baseline_count if baseline_count else 1.0
    count_ratio = candidate_count / baseline_count if baseline_count else 1.0
    high_importance_unmatched_count = sum(
        1
        for item in manual_review_queue
        if item.get("reason") == "high_importance_baseline_unmatched"
    )
    watchlist_unmatched_count = sum(1 for item in manual_review_queue if item.get("watchlist_code"))

    return {
        "summary": {
            "baseline_object_count": baseline_count,
            "candidate_object_count": candidate_count,
            "matched_baseline_count": len(matches),
            "unmatched_baseline_count": len(unmatched_baseline),
            "new_only_count": len(new_only),
            "coverage_rate": round(coverage_rate, 4),
            "candidate_count_ratio": round(count_ratio, 4),
            "below_global_count_gate": baseline_count > 0 and count_ratio < 0.80,
            "high_importance_threshold": high_importance_threshold,
            "high_importance_unmatched_count": high_importance_unmatched_count,
            "watchlist_unmatched_count": watchlist_unmatched_count,
            "importance_delta": _importance_delta_summary(matches),
        },
        "type_distribution": {
            "baseline": dict(Counter(str(obj.get("type", "")) for obj in baseline_objects)),
            "candidate": dict(Counter(str(obj.get("type", "")) for obj in candidate_objects)),
            "candidate_legacy": dict(
                Counter(
                    str(obj.get("legacy_type", ""))
                    for obj in candidate_objects
                    if obj.get("legacy_type")
                )
            ),
        },
        "meeting_summaries": meeting_summaries,
        "matches": matches,
        "unmatched_baseline": unmatched_baseline,
        "new_only_objects": new_only,
        "manual_review_queue": manual_review_queue,
    }


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# L1 Type Experiment Comparison",
        "",
        "## Summary",
        "",
        f"- Baseline objects: {summary.get('baseline_object_count', 0)}",
        f"- Candidate objects: {summary.get('candidate_object_count', 0)}",
        f"- Matched baseline objects: {summary.get('matched_baseline_count', 0)}",
        f"- Coverage rate: {summary.get('coverage_rate', 0)}",
        f"- Candidate count ratio: {summary.get('candidate_count_ratio', 0)}",
        f"- High-importance unmatched: {summary.get('high_importance_unmatched_count', 0)}",
        f"- Watchlist unmatched: {summary.get('watchlist_unmatched_count', 0)}",
        f"- Below global count gate: {summary.get('below_global_count_gate', False)}",
        "",
        "## Importance Drift",
        "",
    ]
    drift = summary.get("importance_delta", {})
    lines.extend(
        [
            f"- Matched count: {drift.get('matched_count', 0)}",
            f"- Mean abs delta: {drift.get('mean_abs', 0)}",
            f"- P90 abs delta: {drift.get('p90_abs', 0)}",
            f"- Max abs delta: {drift.get('max_abs', 0)}",
            f"- Signed mean delta: {drift.get('signed_mean', 0)}",
            "",
            "## Type Distribution",
            "",
            "### Baseline",
            "",
        ]
    )
    for type_name, count in sorted(report.get("type_distribution", {}).get("baseline", {}).items()):
        lines.append(f"- {type_name}: {count}")
    lines.extend(["", "### Candidate", ""])
    for type_name, count in sorted(report.get("type_distribution", {}).get("candidate", {}).items()):
        lines.append(f"- {type_name}: {count}")
    lines.extend(["", "## Meeting Gates", ""])
    for meeting in report.get("meeting_summaries", []):
        lines.append(
            "- {meeting_id}: baseline={baseline_count}, candidate={candidate_count}, "
            "matched={matched_count}, coverage={coverage_rate}, count_ratio={count_ratio}, "
            "below_count_gate={below_count_gate}".format(**meeting)
        )
    lines.extend(["", "## Manual Review Queue", ""])
    queue = report.get("manual_review_queue", [])
    if not queue:
        lines.append("- No high-importance or watchlist unmatched baseline objects.")
    else:
        for item in queue:
            display_item = dict(item)
            display_item["watchlist_code"] = display_item.get("watchlist_code") or ""
            lines.append(
                "- {meeting_id} {baseline_obj_id} {type} reason={reason} "
                "watchlist={watchlist_code} importance={importance}: {content}".format(
                    **display_item,
                )
            )
    lines.append("")
    return "\n".join(lines)


def write_comparison_outputs(report: dict[str, Any], out_dir: Path | str) -> None:
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "comparison_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "comparison_report.md").write_text(
        _markdown_report(report),
        encoding="utf-8",
    )
    (output / "manual_review_queue.json").write_text(
        json.dumps(report.get("manual_review_queue", []), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare canonical and experiment L1 trees.")
    parser.add_argument("--baseline", required=True, help="Baseline share_mem tree.json.")
    parser.add_argument("--candidate", required=True, help="Experiment tree.json.")
    parser.add_argument("--out", required=True, help="Output directory for comparison reports.")
    parser.add_argument(
        "--high-importance-threshold",
        type=float,
        default=0.70,
        help="Baseline importance threshold for manual review misses.",
    )
    parser.add_argument(
        "--match-threshold",
        type=float,
        default=0.42,
        help="Minimum composite score for baseline-to-candidate matching.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    report = compare_l1_trees(
        load_json(args.baseline),
        load_json(args.candidate),
        high_importance_threshold=args.high_importance_threshold,
        match_threshold=args.match_threshold,
    )
    write_comparison_outputs(report, args.out)
    print(
        "comparison complete: "
        f"{report['summary']['matched_baseline_count']} matched, "
        f"{report['summary']['high_importance_unmatched_count']} high-importance unmatched"
    )


if __name__ == "__main__":
    main()
