"""L0 summary and L2 topic-thread agents for demo-oriented research memory.

This module is deliberately separate from the L1 extraction pipeline. It reads
finished meeting-level L1 artifacts and produces inspectable L2 topic-thread
artifacts plus a UI-friendly memory graph.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LONG_TERM_DIR = Path(__file__).resolve().parents[2]
LEGACY_DIR = LONG_TERM_DIR / "archive" / "legacy_temporal_l2_l3"
for _path in (str(LONG_TERM_DIR), str(LEGACY_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from gemini_clients import create_gemini_client
from io_utils import load_api_keys, save_json, utc_now_iso
from multi_agent_tools import extract_json_object, jaccard, tokenize, unique_strings
from schema import DEFAULT_MODEL_NAME

L2_TOPIC_ACTIONS = {
    "create_thread",
    "attach_thread",
    "retain_l1_only",
    "suppress_low_value",
}

PROMOTABLE_L1_TYPES = {
    "decision",
    "method_change",
    "open_question",
    "result",
    "argument",
}

ADMIN_KEYWORDS = {
    "api key",
    "apikey",
    "報帳",
    "reimbursement",
    "invoice",
    "receipt",
    "deadline",
    "截止",
    "截止日期",
    "meeting time",
    "會議時間",
    "行政",
    "實習申請",
    "履歷",
    "推薦信",
    "信用卡",
    "經費",
    "lab expenses",
}

TOPIC_ALIAS_KEYWORDS: dict[str, set[str]] = {
    "memory_evaluation": {
        "evaluation",
        "evaluate",
        "benchmark",
        "baseline",
        "comparison",
        "compare",
        "prove",
        "demonstrate",
        "performance",
        "評估",
        "基準",
        "比較",
        "證明",
        "展示",
    },
    "memory_retrieval": {
        "retrieval",
        "retrieve",
        "recall",
        "query",
        "ranking",
        "score",
        "scoring",
        "tool",
        "tool-calling",
        "function",
        "檢索",
        "查詢",
        "呼叫",
        "排序",
    },
    "memory_consolidation": {
        "consolidation",
        "forgetting",
        "archive",
        "delete",
        "stale",
        "frequency",
        "density",
        "鞏固",
        "遺忘",
        "封存",
        "刪除",
    },
    "transcript_processing": {
        "transcript",
        "transcription",
        "chunk",
        "segmentation",
        "sentence",
        "idea unit",
        "pre-process",
        "preprocess",
        "逐字稿",
        "切",
        "分段",
        "句子",
        "預處理",
    },
    "data_setup": {
        "dataset",
        "bmr",
        "speaker",
        "diarization",
        "zoom",
        "google meet",
        "online meeting",
        "資料集",
        "語者",
        "線上會議",
    },
    "human_configuration": {
        "user",
        "configurable",
        "customization",
        "category",
        "parameter",
        "人機",
        "使用者",
        "可配置",
        "類別",
        "參數",
    },
}

TOPIC_ALIAS_PRIORITY = [
    "memory_evaluation",
    "memory_retrieval",
    "transcript_processing",
    "memory_consolidation",
    "human_configuration",
    "data_setup",
]

L0_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "meeting_id": {"type": "string"},
        "summary": {"type": "string"},
        "main_topics": {"type": "array", "items": {"type": "string"}},
        "important_decisions": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "meeting_id",
        "summary",
        "main_topics",
        "important_decisions",
        "open_questions",
    ],
    "additionalProperties": False,
}

L2_AMBIGUOUS_LINK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "object",
            "properties": {
                "source_l1_id": {"type": "string"},
                "action": {"type": "string", "enum": sorted(L2_TOPIC_ACTIONS)},
                "target_thread_id": {"type": "string"},
                "proposed_thread_title": {"type": "string"},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": [
                "source_l1_id",
                "action",
                "target_thread_id",
                "proposed_thread_title",
                "confidence",
                "reason",
            ],
            "additionalProperties": False,
        }
    },
    "required": ["decision"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class L2TopicRunResult:
    output_dir: Path
    l0_summary_path: Path
    topics_path: Path
    assignments_path: Path
    ui_graph_path: Path


def resolve_model_name(requested_model: str | None) -> str:
    clean = str(requested_model or "").strip()
    if clean:
        return clean
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL_NAME)


def load_l1_meeting(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"L1 file must contain a JSON object: {path}")
    if isinstance(data.get("memory_objects"), list):
        return data
    meetings = data.get("meetings")
    if isinstance(meetings, list) and len(meetings) == 1 and isinstance(meetings[0], dict):
        return meetings[0]
    raise RuntimeError(
        "L1 file must be a final_meeting_node.json or a tree JSON with exactly one meeting: "
        f"{path}"
    )


def load_l1_meetings(paths: list[Path]) -> list[dict[str, Any]]:
    meetings = [load_l1_meeting(path) for path in paths]
    return sorted(
        meetings,
        key=lambda row: (
            str(row.get("meeting_date") or row.get("timestamp") or ""),
            str(row.get("meeting_id", "")),
        ),
    )


def l1_nodes_for_meeting(meeting: dict[str, Any]) -> list[dict[str, Any]]:
    meeting_id = str(meeting.get("meeting_id", ""))
    output: list[dict[str, Any]] = []
    for obj in meeting.get("memory_objects", []):
        if not isinstance(obj, dict):
            continue
        obj_id = str(obj.get("obj_id", "")).strip()
        if not obj_id:
            continue
        output.append(
            {
                "meeting_id": meeting_id,
                "obj_id": obj_id,
                "type": str(obj.get("type", "")).strip(),
                "content": str(obj.get("content", "")).strip(),
                "importance": _safe_float(obj.get("importance"), 0.5),
                "related_topics": unique_strings(obj.get("related_topics", [])),
                "evidence": str(obj.get("evidence", "")).strip(),
            }
        )
    return output


def build_l0_summary_heuristic(meeting: dict[str, Any]) -> dict[str, Any]:
    nodes = l1_nodes_for_meeting(meeting)
    top_nodes = sorted(
        nodes,
        key=lambda row: (
            float(row.get("importance", 0.0)),
            row.get("type") in {"decision", "method_change", "open_question"},
        ),
        reverse=True,
    )[:5]
    topics: list[str] = []
    for node in top_nodes:
        topics.extend(node.get("related_topics", []))
    if not topics:
        topics = _keywords_from_nodes(top_nodes, limit=5)

    decisions = [
        node["content"]
        for node in top_nodes
        if node.get("type") in {"decision", "method_change"}
    ][:3]
    questions = [
        node["content"] for node in top_nodes if node.get("type") == "open_question"
    ][:3]
    summary_basis = "；".join(node["content"] for node in top_nodes[:2])
    return {
        "agent": "l0_summary_agent",
        "mode": "heuristic",
        "meeting_id": str(meeting.get("meeting_id", "")),
        "summary": summary_basis[:320] if summary_basis else "No L1 memory objects found.",
        "main_topics": unique_strings(topics)[:6],
        "important_decisions": decisions,
        "open_questions": questions,
        "source_l1_ids": [node["obj_id"] for node in top_nodes],
    }


def build_l0_summary_prompt(*, meeting_id: str, transcript: str) -> str:
    return f"""
你是 L0 Meeting Summary Agent。

任務：閱讀單場研究會議逐字稿，輸出一份非常簡短的 meeting overview。
L0 不是長期記憶，只是幫助後續 L2 topic agent 理解這場會議的大意。

請輸出 JSON only，欄位：
- meeting_id
- summary: 2-4 句，說明這場會議主要在推進什麼研究問題
- main_topics: 3-6 個主題
- important_decisions: 最多 5 個
- open_questions: 最多 5 個

Meeting ID: {meeting_id}

Transcript:
{transcript[:60000]}
""".strip()


def call_l0_summary_agent(
    *,
    meeting: dict[str, Any],
    transcript_path: Path,
    model_name: str,
    api_key: str | list[str],
) -> dict[str, Any]:
    transcript = transcript_path.read_text(encoding="utf-8")
    meeting_id = str(meeting.get("meeting_id") or transcript_path.stem)
    client = create_gemini_client(api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=build_l0_summary_prompt(meeting_id=meeting_id, transcript=transcript),
        config={
            "temperature": 0.1,
            "response_mime_type": "application/json",
            "response_json_schema": L0_SUMMARY_SCHEMA,
        },
    )
    data = extract_json_object(response.text or "")
    return {
        "agent": "l0_summary_agent",
        "mode": "llm",
        "meeting_id": str(data.get("meeting_id") or meeting_id),
        "summary": str(data.get("summary", "")).strip(),
        "main_topics": unique_strings(data.get("main_topics", []))[:8],
        "important_decisions": unique_strings(data.get("important_decisions", []))[:8],
        "open_questions": unique_strings(data.get("open_questions", []))[:8],
    }


def build_all_l0_summaries(
    *,
    meetings: list[dict[str, Any]],
    transcript_by_meeting_id: dict[str, Path],
    mode: str,
    model_name: str,
    api_key: str | list[str] | None,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for meeting in meetings:
        meeting_id = str(meeting.get("meeting_id", ""))
        transcript_path = transcript_by_meeting_id.get(meeting_id)
        if mode == "llm":
            if api_key is None:
                raise RuntimeError("L0 llm mode requires an API key.")
            if transcript_path is None:
                raise RuntimeError(f"L0 llm mode missing transcript for meeting {meeting_id}.")
            summaries.append(
                call_l0_summary_agent(
                    meeting=meeting,
                    transcript_path=transcript_path,
                    model_name=model_name,
                    api_key=api_key,
                )
            )
        elif mode == "none":
            summaries.append(
                {
                    "agent": "l0_summary_agent",
                    "mode": "none",
                    "meeting_id": meeting_id,
                    "summary": "",
                    "main_topics": [],
                    "important_decisions": [],
                    "open_questions": [],
                    "source_l1_ids": [],
                }
            )
        else:
            summaries.append(build_l0_summary_heuristic(meeting))
    return summaries


def should_promote_l1(node: dict[str, Any]) -> tuple[bool, str]:
    content = str(node.get("content", ""))
    lowered = content.lower()
    node_type = str(node.get("type", ""))
    importance = float(node.get("importance") or 0.0)
    if any(keyword in lowered or keyword in content for keyword in ADMIN_KEYWORDS):
        return False, "administrative or one-off detail"
    if not content or len(content) < 24:
        return False, "content is too short to form a trackable topic"
    if importance < 0.55 and node_type not in {"decision", "method_change", "open_question"}:
        return False, "low importance and not a durable research-memory type"
    if node_type not in PROMOTABLE_L1_TYPES and importance < 0.72:
        return False, "L1 type is not usually promoted to L2"
    return True, "research-relevant L1 that may belong to a cross-meeting topic"


def topic_match_score(node: dict[str, Any], topic: dict[str, Any]) -> float:
    node_topics = {
        str(item).lower()
        for item in node.get("related_topics", [])
        if str(item).strip()
    }
    topic_keywords = {
        str(item).lower()
        for item in topic.get("keywords", [])
        if str(item).strip()
    }
    topic_overlap = len(node_topics & topic_keywords) / max(1, len(node_topics | topic_keywords))
    text_score = jaccard(_node_text(node), _topic_text(topic))
    return round(max(topic_overlap * 0.95, text_score), 3)


def find_topic_candidates(
    node: dict[str, Any],
    topics: list[dict[str, Any]],
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    scored = [
        {
            "thread_id": topic.get("thread_id", ""),
            "title": topic.get("title", ""),
            "score": topic_match_score(node, topic),
            "keywords": topic.get("keywords", []),
        }
        for topic in topics
    ]
    scored.sort(key=lambda row: row["score"], reverse=True)
    return [row for row in scored[:limit] if float(row["score"]) >= 0.06]


def route_l1_assignment(
    node: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    promote, promote_reason = should_promote_l1(node)
    if not promote:
        action = "suppress_low_value" if "low importance" in promote_reason else "retain_l1_only"
        return {
            "source_l1_id": node["obj_id"],
            "action": action,
            "target_thread_id": "",
            "proposed_thread_title": "",
            "confidence": 0.86,
            "reason": promote_reason,
            "decision_source": "rule",
            "candidate_threads": candidates,
        }

    best = candidates[0] if candidates else None
    second = candidates[1] if len(candidates) > 1 else None
    if best and float(best.get("score", 0.0)) >= 0.26:
        return {
            "source_l1_id": node["obj_id"],
            "action": "attach_thread",
            "target_thread_id": best["thread_id"],
            "proposed_thread_title": "",
            "confidence": min(0.96, 0.68 + float(best.get("score", 0.0))),
            "reason": "strong topic keyword/content match",
            "decision_source": "rule",
            "candidate_threads": candidates,
        }
    if (
        best
        and second
        and float(best.get("score", 0.0)) >= 0.13
        and abs(float(best.get("score", 0.0)) - float(second.get("score", 0.0))) <= 0.05
    ):
        return {
            "source_l1_id": node["obj_id"],
            "action": "attach_thread",
            "target_thread_id": best["thread_id"],
            "proposed_thread_title": "",
            "confidence": 0.52,
            "reason": "ambiguous: multiple similar candidate topics",
            "decision_source": "needs_llm",
            "candidate_threads": candidates,
        }
    if best and 0.13 <= float(best.get("score", 0.0)) < 0.26:
        return {
            "source_l1_id": node["obj_id"],
            "action": "attach_thread",
            "target_thread_id": best["thread_id"],
            "proposed_thread_title": "",
            "confidence": 0.58,
            "reason": "ambiguous: weak but plausible candidate topic",
            "decision_source": "needs_llm",
            "candidate_threads": candidates,
        }

    return {
        "source_l1_id": node["obj_id"],
        "action": "create_thread",
        "target_thread_id": "",
        "proposed_thread_title": propose_topic_title(node),
        "confidence": 0.78,
        "reason": promote_reason + "; no existing topic matched strongly",
        "decision_source": "rule",
        "candidate_threads": candidates,
    }


def l1_topic_signature(node: dict[str, Any]) -> set[str]:
    text = _node_text(node).lower()
    signature: set[str] = set()
    for alias, keywords in TOPIC_ALIAS_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            signature.add(alias)
    for topic in node.get("related_topics", []):
        clean = str(topic).strip().lower()
        if clean:
            signature.add(clean)
    return signature


def primary_l1_topic_alias(node: dict[str, Any]) -> str:
    signature = l1_topic_signature(node)
    for alias in TOPIC_ALIAS_PRIORITY:
        if alias in signature:
            return alias
    return ""


def l1_pair_topic_score(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_signature = l1_topic_signature(left)
    right_signature = l1_topic_signature(right)
    signature_score = len(left_signature & right_signature) / max(
        1,
        len(left_signature | right_signature),
    )
    text_score = jaccard(_node_text(left), _node_text(right))
    type_bonus = 0.03 if left.get("type") == right.get("type") else 0.0
    shared_aliases = {
        alias
        for alias in TOPIC_ALIAS_KEYWORDS
        if alias in left_signature and alias in right_signature
    }
    alias_bonus = 0.08 if shared_aliases else 0.0
    return round(max(signature_score * 0.72, text_score) + type_bonus + alias_bonus, 3)


def cluster_l1_topic_groups(
    nodes: list[dict[str, Any]],
    *,
    min_attach_score: float = 0.2,
) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    sorted_nodes = sorted(
        nodes,
        key=lambda row: (
            str(row.get("meeting_id", "")),
            -float(row.get("importance") or 0.0),
            str(row.get("obj_id", "")),
        ),
    )
    for node in sorted_nodes:
        best_cluster: dict[str, Any] | None = None
        best_score = 0.0
        node_primary_alias = primary_l1_topic_alias(node)
        for cluster in clusters:
            cluster_primary_alias = str(cluster.get("primary_alias", ""))
            if node_primary_alias and cluster_primary_alias and node_primary_alias != cluster_primary_alias:
                continue
            scores = [
                l1_pair_topic_score(node, member)
                for member in cluster.get("members", [])
            ]
            score = max(scores) if scores else 0.0
            if score > best_score:
                best_score = score
                best_cluster = cluster
        if best_cluster is not None and best_score >= min_attach_score:
            best_cluster["members"].append(node)
            best_cluster["attach_scores"][node["obj_id"]] = best_score
        else:
            clusters.append(
                {
                    "cluster_id": f"C-L2-{len(clusters) + 1:03d}",
                    "primary_alias": node_primary_alias,
                    "members": [node],
                    "attach_scores": {node["obj_id"]: 1.0},
                }
            )
    return rebalance_l1_topic_groups(clusters)


def rebalance_l1_topic_groups(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge clusters that only become obvious after both groups exist."""
    merged = True
    while merged:
        merged = False
        for left_index, left in enumerate(list(clusters)):
            for right_index in range(left_index + 1, len(clusters)):
                right = clusters[right_index]
                if cluster_similarity(left, right) < 0.24:
                    continue
                left["members"].extend(right.get("members", []))
                left["attach_scores"].update(right.get("attach_scores", {}))
                del clusters[right_index]
                merged = True
                break
            if merged:
                break
    for index, cluster in enumerate(clusters, start=1):
        cluster["cluster_id"] = f"C-L2-{index:03d}"
    return clusters


def cluster_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_primary = str(left.get("primary_alias", ""))
    right_primary = str(right.get("primary_alias", ""))
    if left_primary and right_primary and left_primary != right_primary:
        return 0.0
    left_members = left.get("members", [])
    right_members = right.get("members", [])
    pair_scores = [
        l1_pair_topic_score(left_node, right_node)
        for left_node in left_members
        for right_node in right_members
    ]
    if not pair_scores:
        return 0.0
    left_signature = set().union(*(l1_topic_signature(node) for node in left_members))
    right_signature = set().union(*(l1_topic_signature(node) for node in right_members))
    signature_score = len(left_signature & right_signature) / max(
        1,
        len(left_signature | right_signature),
    )
    return round(max(max(pair_scores), signature_score * 0.82), 3)


def topic_from_l1_cluster(cluster: dict[str, Any], next_topic_index: int) -> dict[str, Any]:
    members = list(cluster.get("members", []))
    representative = max(
        members,
        key=lambda row: (float(row.get("importance") or 0.0), len(str(row.get("content", "")))),
    )
    now = utc_now_iso()
    return {
        "thread_id": new_topic_id(next_topic_index),
        "title": propose_cluster_topic_title(
            members,
            primary_alias=str(cluster.get("primary_alias", "")),
        ),
        "description": propose_cluster_topic_description(members, representative),
        "keywords": propose_cluster_topic_keywords(members),
        "status": "active",
        "importance": max(float(node.get("importance") or 0.0) for node in members),
        "source_l1_ids": [node["obj_id"] for node in members],
        "created_by_meeting": members[0].get("meeting_id", ""),
        "last_updated_meeting": members[-1].get("meeting_id", ""),
        "created_at": now,
        "updated_at": now,
        "cluster_id": cluster.get("cluster_id", ""),
    }


def build_batch_l2_assignments(
    *,
    all_nodes: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    topics: list[dict[str, Any]],
    promotion_reason_by_l1_id: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    topic_by_cluster_id = {
        str(topic.get("cluster_id", "")): topic
        for topic in topics
        if topic.get("cluster_id")
    }
    cluster_by_l1_id: dict[str, dict[str, Any]] = {}
    for cluster in clusters:
        for member in cluster.get("members", []):
            cluster_by_l1_id[member["obj_id"]] = cluster

    assignments: list[dict[str, Any]] = []
    topic_candidates_by_l1: dict[str, list[dict[str, Any]]] = {}
    routing_decisions: list[dict[str, Any]] = []
    for node in all_nodes:
        cluster = cluster_by_l1_id.get(node["obj_id"])
        if cluster is None:
            promote, promote_reason = should_promote_l1(node)
            action = "suppress_low_value" if "low importance" in promote_reason else "retain_l1_only"
            assignment = {
                "source_l1_id": node["obj_id"],
                "action": action,
                "target_thread_id": "",
                "proposed_thread_title": "",
                "confidence": 0.86,
                "reason": promote_reason,
                "decision_source": "batch_promotion_filter",
                "candidate_threads": [],
                "applied": True,
            }
            assignments.append(assignment)
            routing_decisions.append(deepcopy(assignment))
            topic_candidates_by_l1[node["obj_id"]] = []
            continue

        topic = topic_by_cluster_id[str(cluster.get("cluster_id", ""))]
        members = cluster.get("members", [])
        action = "create_thread" if node["obj_id"] == members[0]["obj_id"] else "attach_thread"
        candidates = [
            {
                "thread_id": topic["thread_id"],
                "title": topic["title"],
                "score": cluster.get("attach_scores", {}).get(node["obj_id"], 1.0),
                "keywords": topic.get("keywords", []),
            }
        ]
        assignment = {
            "source_l1_id": node["obj_id"],
            "action": action,
            "target_thread_id": topic["thread_id"],
            "proposed_thread_title": topic["title"] if action == "create_thread" else "",
            "confidence": _clamp(
                0.72 + float(cluster.get("attach_scores", {}).get(node["obj_id"], 0.0)) * 0.2,
                0.62,
                0.96,
            ),
            "reason": (
                promotion_reason_by_l1_id.get(node["obj_id"], "")
                + "; batch topic induction grouped this L1 with related L1 nodes"
            ).strip("; "),
            "decision_source": "batch_cluster",
            "candidate_threads": candidates,
            "applied": True,
        }
        assignments.append(assignment)
        routing_decisions.append(deepcopy(assignment))
        topic_candidates_by_l1[node["obj_id"]] = candidates
    return assignments, topic_candidates_by_l1, routing_decisions


def build_l2_ambiguous_link_prompt(
    *,
    node: dict[str, Any],
    candidate_topics: list[dict[str, Any]],
) -> str:
    return f"""
你是 L2 Topic Thread Memory Agent 的 ambiguous linker。

請只判斷這個 L1 是否應該接到候選 L2 topic，或建立新 topic，或留在 L1。
規則：
- L1 不要改寫。
- L2 是跨會議 topic thread，不是所有 L1 都要進 L2。
- 不要因字面相似硬接，要判斷是不是同一個持續研究議題。
- action 只能是 create_thread, attach_thread, retain_l1_only, suppress_low_value。
- 如果 attach_thread，target_thread_id 必須來自 candidate topics。

L1:
{json.dumps(_slim_l1(node), ensure_ascii=False, indent=2)}

Candidate L2 topics:
{json.dumps(candidate_topics, ensure_ascii=False, indent=2)}

Return JSON only.
""".strip()


def call_l2_ambiguous_linker(
    *,
    node: dict[str, Any],
    candidate_topics: list[dict[str, Any]],
    model_name: str,
    api_key: str | list[str],
) -> dict[str, Any]:
    client = create_gemini_client(api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=build_l2_ambiguous_link_prompt(
            node=node,
            candidate_topics=candidate_topics,
        ),
        config={
            "temperature": 0.1,
            "response_mime_type": "application/json",
            "response_json_schema": L2_AMBIGUOUS_LINK_SCHEMA,
        },
    )
    data = extract_json_object(response.text or "")
    decision = data.get("decision", {})
    if not isinstance(decision, dict):
        raise RuntimeError("L2 ambiguous linker did not return a decision object.")
    return normalize_assignment_decision(decision, node=node, candidates=candidate_topics)


def normalize_assignment_decision(
    decision: dict[str, Any],
    *,
    node: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_ids = {str(row.get("thread_id", "")) for row in candidates}
    action = str(decision.get("action", "")).strip()
    if action not in L2_TOPIC_ACTIONS:
        action = "retain_l1_only"
    target = str(decision.get("target_thread_id", "")).strip()
    if action == "attach_thread" and target not in candidate_ids:
        action = "create_thread"
        target = ""
    if action in {"retain_l1_only", "suppress_low_value", "create_thread"}:
        target = ""
    return {
        "source_l1_id": node["obj_id"],
        "action": action,
        "target_thread_id": target,
        "proposed_thread_title": str(decision.get("proposed_thread_title", "")).strip(),
        "confidence": _clamp(_safe_float(decision.get("confidence"), 0.5), 0.0, 1.0),
        "reason": str(decision.get("reason", "")).strip() or "normalized L2 decision",
        "decision_source": str(decision.get("decision_source", "llm")).strip() or "llm",
        "candidate_threads": candidates,
    }


def apply_l2_assignment(
    *,
    meeting: dict[str, Any],
    node: dict[str, Any],
    topics: list[dict[str, Any]],
    assignment: dict[str, Any],
    next_topic_index: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    topic_by_id = {str(topic.get("thread_id", "")): topic for topic in topics}
    applied = deepcopy(assignment)
    action = str(applied.get("action", "")).strip()
    target_thread_id = str(applied.get("target_thread_id", "")).strip()
    now = utc_now_iso()

    if action == "create_thread":
        target_thread_id = new_topic_id(next_topic_index)
        next_topic_index += 1
        topic = {
            "thread_id": target_thread_id,
            "title": applied.get("proposed_thread_title") or propose_topic_title(node),
            "description": propose_topic_description(node),
            "keywords": propose_topic_keywords(node),
            "status": "active",
            "importance": float(node.get("importance") or 0.5),
            "source_l1_ids": [],
            "created_by_meeting": meeting.get("meeting_id", ""),
            "last_updated_meeting": "",
            "created_at": now,
            "updated_at": now,
        }
        topics.append(topic)
        topic_by_id[target_thread_id] = topic
    elif action == "attach_thread" and target_thread_id not in topic_by_id:
        applied["action"] = "retain_l1_only"
        applied["target_thread_id"] = ""
        applied["applied"] = True
        applied["reason"] = f"{applied.get('reason', '')}; target thread missing"
        return topics, applied, next_topic_index
    elif action in {"retain_l1_only", "suppress_low_value"}:
        applied["target_thread_id"] = ""
        applied["applied"] = True
        return topics, applied, next_topic_index

    topic = topic_by_id[target_thread_id]
    topic["source_l1_ids"] = unique_strings(list(topic.get("source_l1_ids", [])) + [node["obj_id"]])
    topic["keywords"] = unique_strings(list(topic.get("keywords", [])) + propose_topic_keywords(node))[:12]
    topic["importance"] = max(float(topic.get("importance") or 0.0), float(node.get("importance") or 0.0))
    topic["last_updated_meeting"] = meeting.get("meeting_id", "")
    topic["updated_at"] = now
    if not topic.get("description"):
        topic["description"] = propose_topic_description(node)
    applied["target_thread_id"] = target_thread_id
    applied["applied"] = True
    return topics, applied, next_topic_index


def detect_topic_maintenance_warnings(
    *,
    topics: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for left_index, left in enumerate(topics):
        for right in topics[left_index + 1 :]:
            score = jaccard(_topic_text(left), _topic_text(right))
            keyword_overlap = _keyword_overlap(left.get("keywords", []), right.get("keywords", []))
            if score >= 0.34 or keyword_overlap >= 0.5:
                warnings.append(
                    {
                        "type": "possible_topic_merge",
                        "thread_ids": [left.get("thread_id", ""), right.get("thread_id", "")],
                        "confidence": round(max(score, keyword_overlap), 3),
                        "reason": "topic text or keywords overlap strongly; review before merging",
                    }
                )
    for topic in topics:
        source_count = len(topic.get("source_l1_ids", []))
        keyword_count = len(topic.get("keywords", []))
        if source_count >= 8 and keyword_count >= 10:
            warnings.append(
                {
                    "type": "topic_too_broad",
                    "thread_ids": [topic.get("thread_id", "")],
                    "confidence": 0.72,
                    "reason": "topic has many L1 nodes and many keywords; consider splitting after UI review",
                }
            )
        if source_count <= 1 and float(topic.get("importance") or 0.0) < 0.58:
            warnings.append(
                {
                    "type": "possible_archive",
                    "thread_ids": [topic.get("thread_id", "")],
                    "confidence": 0.62,
                    "reason": "topic has only one low-importance L1; keep visible but do not highlight",
                }
            )
    low_confidence = [
        row
        for row in assignments
        if row.get("applied") and float(row.get("confidence") or 0.0) < 0.62
    ]
    for row in low_confidence:
        warnings.append(
            {
                "type": "low_confidence_assignment",
                "source_l1_id": row.get("source_l1_id", ""),
                "thread_ids": [row.get("target_thread_id", "")]
                if row.get("target_thread_id")
                else [],
                "confidence": row.get("confidence", 0.0),
                "reason": row.get("reason", ""),
            }
        )
    return warnings


def validate_l2_outputs(
    *,
    topics: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    all_l1_nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    topic_ids = {str(topic.get("thread_id", "")) for topic in topics}
    l1_ids = {str(node.get("obj_id", "")) for node in all_l1_nodes}
    assigned_ids = [str(row.get("source_l1_id", "")) for row in assignments]

    missing_assignments = sorted(l1_ids - set(assigned_ids))
    if missing_assignments:
        errors.append(f"missing assignments for L1 ids: {', '.join(missing_assignments)}")
    duplicate_ids = sorted({item for item in assigned_ids if assigned_ids.count(item) > 1})
    if duplicate_ids:
        errors.append(f"duplicate assignments for L1 ids: {', '.join(duplicate_ids)}")

    for topic in topics:
        if not topic.get("thread_id"):
            errors.append("topic missing thread_id")
        if not topic.get("title"):
            errors.append(f"topic {topic.get('thread_id', '')} missing title")
        importance = float(topic.get("importance") or 0.0)
        if not 0.0 <= importance <= 1.0:
            errors.append(f"topic {topic.get('thread_id', '')} importance out of range")
    for row in assignments:
        action = str(row.get("action", ""))
        target = str(row.get("target_thread_id", ""))
        if action not in L2_TOPIC_ACTIONS:
            errors.append(f"illegal action for {row.get('source_l1_id', '')}: {action}")
        if action == "attach_thread" and target not in topic_ids:
            errors.append(f"attach target missing for {row.get('source_l1_id', '')}: {target}")
        if action in {"retain_l1_only", "suppress_low_value"} and target:
            errors.append(f"{action} should not have target_thread_id for {row.get('source_l1_id', '')}")
        if float(row.get("confidence") or 0.0) < 0.55:
            warnings.append(f"low confidence assignment: {row.get('source_l1_id', '')}")
    return {
        "agent": "l2_output_verifier",
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "topics": len(topics),
            "assignments": len(assignments),
            "l1_nodes": len(all_l1_nodes),
        },
    }


def build_ui_memory_graph(
    *,
    meetings: list[dict[str, Any]],
    topics: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    l1_by_id = {
        node["obj_id"]: node
        for meeting in meetings
        for node in l1_nodes_for_meeting(meeting)
    }
    graph_nodes: list[dict[str, Any]] = []
    graph_edges: list[dict[str, Any]] = []
    for meeting in meetings:
        meeting_id = str(meeting.get("meeting_id", ""))
        graph_nodes.append(
            {
                "id": f"M-{meeting_id}",
                "level": "meeting",
                "label": meeting_id,
                "summary": str(meeting.get("summary", "")),
            }
        )
    for topic in topics:
        graph_nodes.append(
            {
                "id": topic.get("thread_id", ""),
                "level": "l2_topic",
                "label": topic.get("title", ""),
                "description": topic.get("description", ""),
                "importance": topic.get("importance", 0.0),
                "keywords": topic.get("keywords", []),
                "status": topic.get("status", "active"),
            }
        )
        for source_l1_id in topic.get("source_l1_ids", []):
            node = l1_by_id.get(source_l1_id)
            if not node:
                continue
            l1_graph_id = f"L1-{source_l1_id}"
            graph_nodes.append(
                {
                    "id": l1_graph_id,
                    "level": "l1",
                    "label": source_l1_id,
                    "type": node.get("type", ""),
                    "content": node.get("content", ""),
                    "importance": node.get("importance", 0.0),
                    "meeting_id": node.get("meeting_id", ""),
                    "evidence": node.get("evidence", ""),
                }
            )
            graph_edges.append(
                {
                    "source": topic.get("thread_id", ""),
                    "target": l1_graph_id,
                    "type": "contains_l1",
                }
            )
            graph_edges.append(
                {
                    "source": f"M-{node.get('meeting_id', '')}",
                    "target": l1_graph_id,
                    "type": "meeting_has_l1",
                }
            )

    retained = [
        row
        for row in assignments
        if row.get("action") in {"retain_l1_only", "suppress_low_value"}
    ]
    return {
        "schema": "ui_memory_graph_v1",
        "generated_at": utc_now_iso(),
        "nodes": _dedupe_graph_nodes(graph_nodes),
        "edges": graph_edges,
        "retained_l1_only": retained,
        "ui_hints": {
            "primary_levels": ["meeting", "l2_topic", "l1"],
            "editable_fields": {
                "l2_topic": ["title", "description", "keywords", "status", "importance"],
                "l1": ["importance", "type", "content", "status"],
            },
        },
    }


def run_l2_topic_agents(
    *,
    l1_files: list[Path],
    output_dir: Path,
    transcript_by_meeting_id: dict[str, Path] | None = None,
    l0_mode: str = "heuristic",
    allow_llm_linking: bool = False,
    model_name: str = DEFAULT_MODEL_NAME,
    api_key: str | list[str] | None = None,
) -> L2TopicRunResult:
    meetings = load_l1_meetings(l1_files)
    transcript_by_meeting_id = transcript_by_meeting_id or {}
    output_dir.mkdir(parents=True, exist_ok=True)

    all_l0_summaries = build_all_l0_summaries(
        meetings=meetings,
        transcript_by_meeting_id=transcript_by_meeting_id,
        mode=l0_mode,
        model_name=model_name,
        api_key=api_key,
    )
    l0_summary_doc = {
        "agent": "l0_summary_agent",
        "generated_at": utc_now_iso(),
        "mode": l0_mode,
        "meetings": all_l0_summaries,
    }
    save_json(output_dir / "00_l0_summary_agent_outputs.json", l0_summary_doc)

    topics: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]]
    promotion_candidates: list[dict[str, Any]] = []
    topic_candidates_by_l1: dict[str, list[dict[str, Any]]]
    routing_decisions: list[dict[str, Any]]
    llm_link_decisions: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    all_l1_nodes = [node for meeting in meetings for node in l1_nodes_for_meeting(meeting)]
    promotable_nodes: list[dict[str, Any]] = []
    promotion_reason_by_l1_id: dict[str, str] = {}

    for node in all_l1_nodes:
        promote, promote_reason = should_promote_l1(node)
        promotion_reason_by_l1_id[node["obj_id"]] = promote_reason
        promotion_candidates.append(
            {
                "source_l1_id": node["obj_id"],
                "meeting_id": node["meeting_id"],
                "promote_candidate": promote,
                "reason": promote_reason,
                "type": node.get("type", ""),
                "importance": node.get("importance", 0.0),
            }
        )
        if promote:
            promotable_nodes.append(node)

    topic_clusters = cluster_l1_topic_groups(promotable_nodes)
    topics = [
        topic_from_l1_cluster(cluster, index)
        for index, cluster in enumerate(topic_clusters, start=1)
    ]
    assignments, topic_candidates_by_l1, routing_decisions = build_batch_l2_assignments(
        all_nodes=all_l1_nodes,
        clusters=topic_clusters,
        topics=topics,
        promotion_reason_by_l1_id=promotion_reason_by_l1_id,
    )
    for index, assignment in enumerate(assignments, start=1):
        events.append(
            {
                "event_index": index,
                "meeting_id": l1_nodes_by_id(all_l1_nodes).get(
                    assignment.get("source_l1_id", ""),
                    {},
                ).get("meeting_id", ""),
                "source_l1_id": assignment.get("source_l1_id", ""),
                "assignment": assignment,
                "topic_count_before": 0,
                "topic_count_after": len(topics),
            }
        )

    maintenance_report = {
        "agent": "l2_topic_maintenance_agent",
        "generated_at": utc_now_iso(),
        "warnings": detect_topic_maintenance_warnings(
            topics=topics,
            assignments=assignments,
        ),
    }
    validation_report = validate_l2_outputs(
        topics=topics,
        assignments=assignments,
        all_l1_nodes=[node for meeting in meetings for node in l1_nodes_for_meeting(meeting)],
    )
    ui_graph = build_ui_memory_graph(
        meetings=meetings,
        topics=topics,
        assignments=assignments,
    )

    save_json(output_dir / "01_l2_promotion_candidates.json", {"items": promotion_candidates})
    save_json(output_dir / "02_l2_topic_candidates.json", topic_candidates_by_l1)
    save_json(output_dir / "03_l2_assignment_routing.json", {"items": routing_decisions})
    save_json(output_dir / "04_l2_llm_link_decisions.json", {"items": llm_link_decisions})
    save_json(output_dir / "05_l2_l1_assignments.json", {"items": assignments})
    save_json(output_dir / "06_l2_topic_threads.json", {"topics": topics})
    save_json(output_dir / "07_l2_topic_maintenance_report.json", maintenance_report)
    save_json(output_dir / "08_l2_validation_report.json", validation_report)
    save_json(output_dir / "09_l2_ui_memory_graph.json", ui_graph)
    save_json(
        output_dir / "run_summary.json",
        {
            "agent": "l0_l2_topic_pipeline",
            "generated_at": utc_now_iso(),
            "l1_files": [str(path) for path in l1_files],
            "l0_mode": l0_mode,
            "allow_llm_linking": allow_llm_linking,
            "topic_mode": "batch_cluster",
            "counts": {
                "meetings": len(meetings),
                "l1_nodes": len(all_l1_nodes),
                "l2_topics": len(topics),
                "assignments": len(assignments),
                "maintenance_warnings": len(maintenance_report["warnings"]),
            },
            "validation": validation_report,
            "events": events,
        },
    )

    return L2TopicRunResult(
        output_dir=output_dir,
        l0_summary_path=output_dir / "00_l0_summary_agent_outputs.json",
        topics_path=output_dir / "06_l2_topic_threads.json",
        assignments_path=output_dir / "05_l2_l1_assignments.json",
        ui_graph_path=output_dir / "09_l2_ui_memory_graph.json",
    )


def propose_topic_title(node: dict[str, Any]) -> str:
    topics = unique_strings(node.get("related_topics", []))
    if topics:
        return " / ".join(topics[:2])
    keywords = _keywords_from_nodes([node], limit=4)
    if keywords:
        return " / ".join(keywords[:2]).title()
    content = str(node.get("content", "")).strip()
    return content[:48] or "Untitled Topic"


def propose_cluster_topic_title(
    members: list[dict[str, Any]],
    *,
    primary_alias: str = "",
) -> str:
    if primary_alias:
        return _format_topic_alias(primary_alias)
    aliases = _rank_cluster_aliases(members)
    if aliases:
        return " / ".join(_format_topic_alias(alias) for alias in aliases[:2])
    topic_counts: dict[str, int] = {}
    for node in members:
        for topic in node.get("related_topics", []):
            clean = str(topic).strip()
            if clean:
                topic_counts[clean] = topic_counts.get(clean, 0) + 1
    ranked_topics = sorted(topic_counts.items(), key=lambda item: (-item[1], item[0].lower()))
    if ranked_topics:
        return " / ".join(topic for topic, _count in ranked_topics[:2])
    keywords = propose_cluster_topic_keywords(members)
    if keywords:
        return " / ".join(keywords[:2]).title()
    representative = max(members, key=lambda row: float(row.get("importance") or 0.0))
    return propose_topic_title(representative)


def propose_cluster_topic_description(
    members: list[dict[str, Any]],
    representative: dict[str, Any],
) -> str:
    if len(members) == 1:
        return propose_topic_description(representative)
    meetings = unique_strings([node.get("meeting_id", "") for node in members])
    title = propose_cluster_topic_title(members)
    return (
        f"{title} is a topic thread induced from {len(members)} L1 nodes "
        f"across {len(meetings)} meeting(s). Representative L1: "
        f"{representative.get('content', '')[:180]}"
    )


def propose_cluster_topic_keywords(members: list[dict[str, Any]]) -> list[str]:
    aliases = [_format_topic_alias(alias) for alias in _rank_cluster_aliases(members)]
    related_topics: list[str] = []
    for node in members:
        related_topics.extend(node.get("related_topics", []))
    keywords = unique_strings(aliases + related_topics + _keywords_from_nodes(members, limit=12))
    return keywords[:12]


def propose_topic_description(node: dict[str, Any]) -> str:
    content = str(node.get("content", "")).strip()
    if len(content) <= 180:
        return content
    return content[:177].rstrip() + "..."


def propose_topic_keywords(node: dict[str, Any]) -> list[str]:
    topics = unique_strings(node.get("related_topics", []))
    if topics:
        return topics[:10]
    return _keywords_from_nodes([node], limit=8)


def new_topic_id(next_index: int) -> str:
    return f"T-L2-{next_index:03d}"


def parse_transcript_mapping(values: list[str]) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for value in values:
        if "=" in value:
            meeting_id, path_text = value.split("=", 1)
            mapping[meeting_id.strip()] = Path(path_text.strip())
        else:
            path = Path(value)
            mapping[path.stem] = path
    return mapping


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run L0 summary agent and L2 topic-thread agents from finished L1 artifacts."
    )
    parser.add_argument(
        "--l1-files",
        nargs="+",
        required=True,
        type=Path,
        help="final_meeting_node.json files, one per meeting.",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="Directory for l2-named artifacts.",
    )
    parser.add_argument(
        "--transcript",
        action="append",
        default=[],
        help="Optional L0 transcript path. Use 0307=path or a path whose stem is the meeting id.",
    )
    parser.add_argument(
        "--l0-mode",
        choices=["heuristic", "llm", "none"],
        default="heuristic",
        help="L0 summary mode. Use llm to send each transcript once.",
    )
    parser.add_argument(
        "--allow-llm-linking",
        action="store_true",
        help="Call LLM only for ambiguous L2 topic linking decisions.",
    )
    parser.add_argument("--model", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_name = resolve_model_name(args.model)
    needs_api_key = args.l0_mode == "llm" or args.allow_llm_linking
    api_key: str | list[str] | None = load_api_keys() if needs_api_key else None
    result = run_l2_topic_agents(
        l1_files=args.l1_files,
        output_dir=args.out_dir,
        transcript_by_meeting_id=parse_transcript_mapping(args.transcript),
        l0_mode=args.l0_mode,
        allow_llm_linking=args.allow_llm_linking,
        model_name=model_name,
        api_key=api_key,
    )
    print(f"L0/L2 artifacts written to: {result.output_dir}")
    print(f"L0 summary: {result.l0_summary_path}")
    print(f"L2 topics: {result.topics_path}")
    print(f"L2 assignments: {result.assignments_path}")
    print(f"UI graph: {result.ui_graph_path}")


def _node_text(node: dict[str, Any]) -> str:
    return " ".join(
        [
            str(node.get("type", "")),
            str(node.get("content", "")),
            " ".join(str(item) for item in node.get("related_topics", [])),
        ]
    )


def _topic_text(topic: dict[str, Any]) -> str:
    return " ".join(
        [
            str(topic.get("title", "")),
            str(topic.get("description", "")),
            " ".join(str(item) for item in topic.get("keywords", [])),
        ]
    )


def _slim_l1(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "obj_id": node.get("obj_id", ""),
        "meeting_id": node.get("meeting_id", ""),
        "type": node.get("type", ""),
        "importance": node.get("importance", 0.0),
        "content": node.get("content", ""),
        "related_topics": node.get("related_topics", []),
    }


def l1_nodes_by_id(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(node.get("obj_id", "")): node for node in nodes}


def _rank_cluster_aliases(members: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for node in members:
        for alias in l1_topic_signature(node):
            if alias not in TOPIC_ALIAS_KEYWORDS:
                continue
            counts[alias] = counts.get(alias, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [alias for alias, _count in ranked]


def _format_topic_alias(alias: str) -> str:
    return {
        "memory_evaluation": "Memory Evaluation",
        "memory_retrieval": "Memory Retrieval",
        "memory_consolidation": "Memory Consolidation",
        "transcript_processing": "Transcript Processing",
        "data_setup": "Data Setup",
        "human_configuration": "Human Configuration",
    }.get(alias, alias.replace("_", " ").title())


def _keywords_from_nodes(nodes: list[dict[str, Any]], *, limit: int) -> list[str]:
    stopwords = {
        "the",
        "and",
        "that",
        "with",
        "this",
        "from",
        "will",
        "should",
        "into",
        "about",
        "meeting",
        "system",
        "team",
        "model",
        "memory",
    }
    counts: dict[str, int] = {}
    for node in nodes:
        for token in tokenize(str(node.get("content", ""))):
            if len(token) < 4 or token in stopwords:
                continue
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _count in ranked[:limit]]


def _keyword_overlap(left: list[Any], right: list[Any]) -> float:
    left_set = {str(item).lower() for item in left if str(item).strip()}
    right_set = {str(item).lower() for item in right if str(item).strip()}
    return len(left_set & right_set) / max(1, len(left_set | right_set))


def _dedupe_graph_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("id", ""))
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        output.append(node)
    return output


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


if __name__ == "__main__":
    main()
