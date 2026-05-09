"""Thread-style L2 memory demo built from meeting-level L1 objects.

This module is intentionally sidecar-first: it does not replace the existing
phase-summary L2 schema. It produces a replayable demo artifact showing how L1
objects from a sequence of meetings create or update evolving topic threads.
"""

from __future__ import annotations

import argparse
import json
import os
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
from io_utils import load_api_keys, load_tree, save_json, utc_now_iso
from multi_agent_tools import extract_json_object, jaccard, tokenize, unique_strings
from schema import DEFAULT_MODEL_NAME

THREAD_DECISION_ACTIONS = {
    "create_thread",
    "attach_thread",
    "ignore_local_detail",
}

THREAD_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_l1_id": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": sorted(THREAD_DECISION_ACTIONS),
                    },
                    "target_thread_id": {"type": "string"},
                    "title": {"type": "string"},
                    "topic_path": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                    "episode_summary": {"type": "string"},
                    "change_type": {
                        "type": "string",
                        "enum": [
                            "new_information",
                            "status_update",
                            "constraint_added",
                            "decision_made",
                            "question_opened",
                            "question_resolved",
                            "todo_added",
                            "result_reported",
                            "method_changed",
                            "background_only",
                        ],
                    },
                    "current_status": {"type": "string"},
                    "current_facts": {"type": "array", "items": {"type": "string"}},
                    "constraints": {"type": "array", "items": {"type": "string"}},
                    "open_questions": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "source_l1_id",
                    "action",
                    "target_thread_id",
                    "title",
                    "topic_path",
                    "reason",
                    "episode_summary",
                    "change_type",
                    "current_status",
                    "current_facts",
                    "constraints",
                    "open_questions",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["decisions"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ThreadL2Result:
    demo: dict[str, Any]
    artifact_path: Path
    viewer_path: Path


def resolve_model_name(requested_model: str | None) -> str:
    clean = str(requested_model or "").strip()
    if clean:
        return clean
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL_NAME)


def _meeting_sort_key(meeting: dict[str, Any]) -> tuple[str, str]:
    return (
        str(meeting.get("meeting_date") or meeting.get("timestamp") or ""),
        str(meeting.get("meeting_id", "")),
    )


def select_meetings(tree: dict[str, Any], meeting_ids: list[str]) -> list[dict[str, Any]]:
    id_set = set(meeting_ids)
    meetings = [m for m in tree.get("meetings", []) if m.get("meeting_id") in id_set]
    found_ids = {str(m.get("meeting_id", "")) for m in meetings}
    missing = [meeting_id for meeting_id in meeting_ids if meeting_id not in found_ids]
    if missing:
        raise RuntimeError(f"Meetings not found in tree: {', '.join(missing)}")
    order = {meeting_id: index for index, meeting_id in enumerate(meeting_ids)}
    return sorted(meetings, key=lambda m: order.get(str(m.get("meeting_id", "")), 10**9))


def l1_nodes_for_meeting(meeting: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    meeting_id = str(meeting.get("meeting_id", ""))
    for obj in meeting.get("memory_objects", []):
        if not isinstance(obj, dict):
            continue
        output.append(
            {
                "meeting_id": meeting_id,
                "obj_id": str(obj.get("obj_id", "")),
                "type": str(obj.get("type", "")),
                "content": str(obj.get("content", "")),
                "importance": obj.get("importance", 0.5),
                "related_topics": obj.get("related_topics", []),
                "evidence": str(obj.get("evidence", ""))[:500],
            }
        )
    return output


def _thread_text(thread: dict[str, Any]) -> str:
    parts = [
        thread.get("title", ""),
        thread.get("current_status", ""),
        " ".join(thread.get("topic_path", [])),
        " ".join(thread.get("current_facts", [])),
        " ".join(thread.get("constraints", [])),
        " ".join(thread.get("open_questions", [])),
    ]
    return " ".join(str(part) for part in parts if part)


def thread_match_score(l1_node: dict[str, Any], thread: dict[str, Any]) -> float:
    content_score = jaccard(l1_node.get("content", ""), _thread_text(thread))
    l1_topics = set(str(t).lower() for t in l1_node.get("related_topics", []) if str(t).strip())
    thread_topics = set(
        str(t).lower()
        for t in list(thread.get("topic_path", []))
        + list(thread.get("keywords", []))
        if str(t).strip()
    )
    topic_score = len(l1_topics & thread_topics) / max(1, len(l1_topics | thread_topics))
    return round(max(content_score, topic_score * 0.9), 3)


def prefilter_threads(
    l1_nodes: list[dict[str, Any]],
    threads: list[dict[str, Any]],
    *,
    max_threads_per_l1: int = 4,
) -> dict[str, list[dict[str, Any]]]:
    candidates: dict[str, list[dict[str, Any]]] = {}
    for node in l1_nodes:
        scored = [
            {
                "thread_id": thread.get("thread_id", ""),
                "title": thread.get("title", ""),
                "topic_path": thread.get("topic_path", []),
                "current_status": thread.get("current_status", ""),
                "score": thread_match_score(node, thread),
            }
            for thread in threads
        ]
        scored.sort(key=lambda row: row["score"], reverse=True)
        candidates[node["obj_id"]] = [
            row for row in scored[:max_threads_per_l1] if float(row["score"]) >= 0.08
        ]
    return candidates


def _slim_l1_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "obj_id": node.get("obj_id", ""),
        "type": node.get("type", ""),
        "importance": node.get("importance", 0.5),
        "content": node.get("content", ""),
        "related_topics": node.get("related_topics", []),
    }


def _slim_thread(thread: dict[str, Any]) -> dict[str, Any]:
    return {
        "thread_id": thread.get("thread_id", ""),
        "title": thread.get("title", ""),
        "topic_path": thread.get("topic_path", []),
        "current_status": thread.get("current_status", ""),
        "current_facts": thread.get("current_facts", [])[-6:],
        "constraints": thread.get("constraints", [])[-6:],
        "open_questions": thread.get("open_questions", [])[-4:],
        "last_updated_meeting": thread.get("last_updated_meeting", ""),
    }


def build_thread_link_prompt(
    *,
    meeting: dict[str, Any],
    l1_nodes: list[dict[str, Any]],
    threads: list[dict[str, Any]],
    candidate_threads_by_l1: dict[str, list[dict[str, Any]]],
) -> str:
    return f"""
你是 L2 thread memory updater。
任務：把單場 meeting 的 L1 memory objects 接到跨 meeting 的 topic/thread memory。

重要原則：
- L1 是 meeting-level event，不要改寫或覆蓋 L1。
- L2 thread 是 append-only episode history + current state。
- 如果 L1 只是非常局部、一次性的細節，且不值得跨 meeting 追蹤，action=ignore_local_detail。
- 如果 L1 屬於既有 thread，action=attach_thread，並更新 current_status/facts/constraints/open_questions。
- 如果 L1 是值得追蹤的新主題，action=create_thread。
- 不要因為字面相似就硬接；要判斷是否為同一個持續議題。
- 回傳的 decisions 必須涵蓋每個 L1 obj_id。

Meeting:
{json.dumps({"meeting_id": meeting.get("meeting_id"), "meeting_date": meeting.get("meeting_date"), "timestamp": meeting.get("timestamp")}, ensure_ascii=False, indent=2)}

Existing L2 threads:
{json.dumps([_slim_thread(thread) for thread in threads], ensure_ascii=False, indent=2)}

Rule-prefiltered candidate threads by L1:
{json.dumps(candidate_threads_by_l1, ensure_ascii=False, indent=2)}

New L1 nodes from this meeting:
{json.dumps([_slim_l1_node(node) for node in l1_nodes], ensure_ascii=False, indent=2)}

Return JSON only.
""".strip()


def call_thread_linker(
    *,
    model_name: str,
    api_key: str | list[str],
    meeting: dict[str, Any],
    l1_nodes: list[dict[str, Any]],
    threads: list[dict[str, Any]],
    candidate_threads_by_l1: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    client = create_gemini_client(api_key)
    prompt = build_thread_link_prompt(
        meeting=meeting,
        l1_nodes=l1_nodes,
        threads=threads,
        candidate_threads_by_l1=candidate_threads_by_l1,
    )
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config={
            "temperature": 0.1,
            "response_mime_type": "application/json",
            "response_json_schema": THREAD_DECISION_SCHEMA,
        },
    )
    data = extract_json_object(response.text or "")
    decisions = data.get("decisions", [])
    return [row for row in decisions if isinstance(row, dict)]


def _topic_path_from_l1(node: dict[str, Any]) -> list[str]:
    topics = unique_strings(node.get("related_topics", []))
    if topics:
        return topics[:3]
    tokens = sorted(tokenize(node.get("content", "")))
    return tokens[:3] or ["未分類議題"]


def heuristic_thread_decisions(
    *,
    l1_nodes: list[dict[str, Any]],
    threads: list[dict[str, Any]],
    candidate_threads_by_l1: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for node in l1_nodes:
        candidates = candidate_threads_by_l1.get(node["obj_id"], [])
        best = candidates[0] if candidates else None
        importance = float(node.get("importance") or 0.5)
        if best and float(best.get("score", 0.0)) >= 0.18:
            decisions.append(
                {
                    "source_l1_id": node["obj_id"],
                    "action": "attach_thread",
                    "target_thread_id": best["thread_id"],
                    "title": best.get("title", ""),
                    "topic_path": best.get("topic_path", []),
                    "reason": "heuristic attach by related topic/content similarity",
                    "episode_summary": node.get("content", "")[:160],
                    "change_type": _change_type_for_l1(node),
                    "current_status": "",
                    "current_facts": [node.get("content", "")[:120]],
                    "constraints": [],
                    "open_questions": [node.get("content", "")[:120]]
                    if node.get("type") == "open_question"
                    else [],
                }
            )
        elif importance < 0.58 and node.get("type") not in {"decision", "method_change", "open_question"}:
            decisions.append(
                {
                    "source_l1_id": node["obj_id"],
                    "action": "ignore_local_detail",
                    "target_thread_id": "",
                    "title": "",
                    "topic_path": [],
                    "reason": "heuristic ignored low-importance local detail",
                    "episode_summary": "",
                    "change_type": "background_only",
                    "current_status": "",
                    "current_facts": [],
                    "constraints": [],
                    "open_questions": [],
                }
            )
        else:
            title = _title_from_l1(node)
            decisions.append(
                {
                    "source_l1_id": node["obj_id"],
                    "action": "create_thread",
                    "target_thread_id": "",
                    "title": title,
                    "topic_path": _topic_path_from_l1(node),
                    "reason": "heuristic created new thread because no strong match existed",
                    "episode_summary": node.get("content", "")[:160],
                    "change_type": _change_type_for_l1(node),
                    "current_status": node.get("content", "")[:160],
                    "current_facts": [node.get("content", "")[:120]],
                    "constraints": [],
                    "open_questions": [node.get("content", "")[:120]]
                    if node.get("type") == "open_question"
                    else [],
                }
            )
    return decisions


def _change_type_for_l1(node: dict[str, Any]) -> str:
    obj_type = node.get("type", "")
    return {
        "decision": "decision_made",
        "todo": "todo_added",
        "method_change": "method_changed",
        "result": "result_reported",
        "open_question": "question_opened",
        "argument": "new_information",
    }.get(obj_type, "new_information")


def _title_from_l1(node: dict[str, Any]) -> str:
    topics = unique_strings(node.get("related_topics", []))
    if topics:
        return " / ".join(topics[:2])
    content = str(node.get("content", "")).strip()
    return content[:32] or "未命名 thread"


def _new_thread_id(next_index: int) -> str:
    return f"T-{next_index:03d}"


def apply_thread_decisions(
    *,
    meeting: dict[str, Any],
    l1_nodes: list[dict[str, Any]],
    threads: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    next_thread_index: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    node_by_id = {node["obj_id"]: node for node in l1_nodes}
    thread_by_id = {thread["thread_id"]: thread for thread in threads}
    normalized_decisions: list[dict[str, Any]] = []

    for decision in decisions:
        source_l1_id = str(decision.get("source_l1_id", ""))
        node = node_by_id.get(source_l1_id)
        if not node:
            continue
        action = str(decision.get("action", "")).strip()
        if action not in THREAD_DECISION_ACTIONS:
            action = "ignore_local_detail"
        target_thread_id = str(decision.get("target_thread_id", "")).strip()

        if action == "create_thread" or (
            action == "attach_thread" and target_thread_id not in thread_by_id
        ):
            action = "create_thread"
            target_thread_id = _new_thread_id(next_thread_index)
            next_thread_index += 1
            thread = {
                "thread_id": target_thread_id,
                "title": str(decision.get("title", "")).strip() or _title_from_l1(node),
                "topic_path": unique_strings(decision.get("topic_path", []))
                or _topic_path_from_l1(node),
                "thread_type": "topic_thread",
                "current_status": "",
                "current_facts": [],
                "constraints": [],
                "open_questions": [],
                "episodes": [],
                "source_l1_ids": [],
                "created_by_meeting": meeting.get("meeting_id", ""),
                "last_updated_meeting": "",
                "keywords": unique_strings(node.get("related_topics", [])),
            }
            threads.append(thread)
            thread_by_id[target_thread_id] = thread
        elif action == "ignore_local_detail":
            normalized_decisions.append(
                {
                    **decision,
                    "action": action,
                    "target_thread_id": "",
                    "applied": True,
                }
            )
            continue

        thread = thread_by_id[target_thread_id]
        episode = {
            "meeting_id": meeting.get("meeting_id", ""),
            "source_l1_ids": [source_l1_id],
            "source_l1_type": node.get("type", ""),
            "summary": str(decision.get("episode_summary", "")).strip()
            or node.get("content", ""),
            "change_type": str(decision.get("change_type", "")).strip()
            or _change_type_for_l1(node),
            "reason": str(decision.get("reason", "")).strip(),
        }
        thread.setdefault("episodes", []).append(episode)
        thread["source_l1_ids"] = unique_strings(
            list(thread.get("source_l1_ids", [])) + [source_l1_id]
        )
        thread["keywords"] = unique_strings(
            list(thread.get("keywords", [])) + list(node.get("related_topics", []))
        )
        if decision.get("title"):
            thread["title"] = str(decision.get("title", "")).strip()
        if decision.get("topic_path"):
            thread["topic_path"] = unique_strings(decision.get("topic_path", []))
        if decision.get("current_status"):
            thread["current_status"] = str(decision.get("current_status", "")).strip()
        elif not thread.get("current_status"):
            thread["current_status"] = node.get("content", "")
        thread["current_facts"] = unique_strings(
            list(thread.get("current_facts", []))
            + list(decision.get("current_facts", []))
        )[-12:]
        thread["constraints"] = unique_strings(
            list(thread.get("constraints", [])) + list(decision.get("constraints", []))
        )[-8:]
        thread["open_questions"] = unique_strings(
            list(thread.get("open_questions", []))
            + list(decision.get("open_questions", []))
        )[-8:]
        thread["last_updated_meeting"] = meeting.get("meeting_id", "")
        normalized_decisions.append(
            {
                **decision,
                "action": action,
                "target_thread_id": target_thread_id,
                "applied": True,
            }
        )

    return threads, normalized_decisions, next_thread_index


def _ignore_decision_for_l1(node: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "source_l1_id": node.get("obj_id", ""),
        "action": "ignore_local_detail",
        "target_thread_id": "",
        "title": "",
        "topic_path": [],
        "reason": reason,
        "episode_summary": "",
        "change_type": "background_only",
        "current_status": "",
        "current_facts": [],
        "constraints": [],
        "open_questions": [],
    }


def _thread_ids(threads: list[dict[str, Any]]) -> set[str]:
    return {str(thread.get("thread_id", "")) for thread in threads if thread.get("thread_id")}


def run_thread_l2_demo(
    *,
    tree: dict[str, Any],
    meeting_ids: list[str],
    out_dir: Path,
    model_name: str = DEFAULT_MODEL_NAME,
    api_key: str | list[str] | None = None,
    heuristic_only: bool = False,
) -> ThreadL2Result:
    meetings = select_meetings(tree, meeting_ids)
    threads: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    next_thread_index = 1

    for step_index, meeting in enumerate(meetings, start=1):
        l1_nodes = l1_nodes_for_meeting(meeting)
        meeting_before = deepcopy(threads)
        step_candidate_threads: dict[str, list[dict[str, Any]]] = {}
        step_applied_decisions: list[dict[str, Any]] = []
        if heuristic_only:
            for node in l1_nodes:
                node_candidates = prefilter_threads([node], threads)
                step_candidate_threads.update(node_candidates)
                node_decisions = heuristic_thread_decisions(
                    l1_nodes=[node],
                    threads=threads,
                    candidate_threads_by_l1=node_candidates,
                )
                event_before = deepcopy(threads)
                before_ids = _thread_ids(event_before)
                threads, applied, next_thread_index = apply_thread_decisions(
                    meeting=meeting,
                    l1_nodes=[node],
                    threads=threads,
                    decisions=node_decisions,
                    next_thread_index=next_thread_index,
                )
                event_after = deepcopy(threads)
                applied_decision = (
                    applied[0]
                    if applied
                    else _ignore_decision_for_l1(node, "no heuristic decision was applied")
                )
                step_applied_decisions.extend(applied)
                after_ids = _thread_ids(event_after)
                events.append(
                    {
                        "event_index": len(events) + 1,
                        "step_index": step_index,
                        "meeting_id": meeting.get("meeting_id", ""),
                        "meeting_date": meeting.get("meeting_date", ""),
                        "timestamp": meeting.get("timestamp", ""),
                        "l1_node": node,
                        "candidate_threads": node_candidates.get(node["obj_id"], []),
                        "decision": applied_decision,
                        "threads_before": event_before,
                        "threads_after": event_after,
                        "created_thread_ids": sorted(after_ids - before_ids),
                        "updated_thread_ids": sorted(
                            {
                                applied_decision.get("target_thread_id", "")
                            }
                            if applied_decision.get("action") == "attach_thread"
                            and applied_decision.get("target_thread_id")
                            else set()
                        ),
                    }
                )
        else:
            if api_key is None:
                raise RuntimeError("api_key is required unless heuristic_only=True")
            step_candidate_threads = prefilter_threads(l1_nodes, threads)
            decisions = call_thread_linker(
                model_name=model_name,
                api_key=api_key,
                meeting=meeting,
                l1_nodes=l1_nodes,
                threads=threads,
                candidate_threads_by_l1=step_candidate_threads,
            )
            decision_by_l1_id = {
                str(decision.get("source_l1_id", "")): decision
                for decision in decisions
                if isinstance(decision, dict)
            }
            for node in l1_nodes:
                decision = decision_by_l1_id.get(node["obj_id"]) or _ignore_decision_for_l1(
                    node, "LLM did not return a decision for this L1 node"
                )
                event_before = deepcopy(threads)
                before_ids = _thread_ids(event_before)
                threads, applied, next_thread_index = apply_thread_decisions(
                    meeting=meeting,
                    l1_nodes=[node],
                    threads=threads,
                    decisions=[decision],
                    next_thread_index=next_thread_index,
                )
                event_after = deepcopy(threads)
                applied_decision = (
                    applied[0]
                    if applied
                    else _ignore_decision_for_l1(node, "LLM decision was not applied")
                )
                step_applied_decisions.extend(applied)
                after_ids = _thread_ids(event_after)
                events.append(
                    {
                        "event_index": len(events) + 1,
                        "step_index": step_index,
                        "meeting_id": meeting.get("meeting_id", ""),
                        "meeting_date": meeting.get("meeting_date", ""),
                        "timestamp": meeting.get("timestamp", ""),
                        "l1_node": node,
                        "candidate_threads": step_candidate_threads.get(node["obj_id"], []),
                        "decision": applied_decision,
                        "threads_before": event_before,
                        "threads_after": event_after,
                        "created_thread_ids": sorted(after_ids - before_ids),
                        "updated_thread_ids": sorted(
                            {
                                applied_decision.get("target_thread_id", "")
                            }
                            if applied_decision.get("action") == "attach_thread"
                            and applied_decision.get("target_thread_id")
                            else set()
                        ),
                    }
                )
        after = deepcopy(threads)
        step = {
            "step_index": step_index,
            "meeting_id": meeting.get("meeting_id", ""),
            "meeting_date": meeting.get("meeting_date", ""),
            "timestamp": meeting.get("timestamp", ""),
            "new_l1_nodes": l1_nodes,
            "candidate_threads_by_l1": step_candidate_threads,
            "decisions": step_applied_decisions,
            "threads_before": meeting_before,
            "threads_after": after,
            "created_thread_ids": sorted(
                set(t["thread_id"] for t in after)
                - set(t["thread_id"] for t in meeting_before)
            ),
            "updated_thread_ids": sorted(
                {
                    d.get("target_thread_id", "")
                    for d in step_applied_decisions
                    if d.get("action") == "attach_thread" and d.get("target_thread_id")
                }
            ),
        }
        steps.append(step)

    demo = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "mode": "heuristic" if heuristic_only else "llm",
        "meeting_ids": [m.get("meeting_id", "") for m in meetings],
        "steps": steps,
        "events": events,
        "final_threads": threads,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = out_dir / "thread_l2_demo.json"
    save_json(artifact_path, demo)
    viewer_path = out_dir / "thread_l2_viewer.html"
    viewer_path.write_text(THREAD_L2_VIEWER_HTML, encoding="utf-8")
    memory_tree_path = out_dir / "thread_l2_memory_tree.html"
    memory_tree_path.write_text(THREAD_L2_VIEWER_HTML, encoding="utf-8")
    return ThreadL2Result(demo=demo, artifact_path=artifact_path, viewer_path=viewer_path)


THREAD_L2_VIEWER_HTML = r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>L2 Dynamic Thread Tree</title>
  <style>
    :root{--bg:#f4f6f8;--panel:#fff;--ink:#17202a;--muted:#667085;--line:#d6dee8;--soft:#eef3f7;--root:#17313a;--new:#1d4ed8;--newsoft:#e6efff;--upd:#087568;--updsoft:#daf4ee;--ign:#8a4b00;--ignsoft:#fff2d6;--hot:#f59e0b;--shadow:0 14px 32px rgba(15,23,42,.08);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink)}header{background:#10242a;color:#fff;padding:14px 22px;display:flex;justify-content:space-between;align-items:center;gap:16px}h1{font-size:18px;margin:0}.sub{font-size:13px;color:#a8c1c8;margin-top:3px}.metrics{display:flex;gap:8px;flex-wrap:wrap}.metric{border:1px solid rgba(255,255,255,.18);border-radius:7px;padding:6px 10px;background:rgba(255,255,255,.06)}.metric strong{display:block}.metric span{font-size:11px;color:#a8c1c8}
    main{display:grid;grid-template-columns:310px minmax(580px,1fr)390px;gap:14px;padding:14px;min-height:calc(100vh - 72px)}.panel{background:#fff;border:1px solid var(--line);border-radius:9px;overflow:hidden;box-shadow:var(--shadow);min-height:0}.head{padding:12px 14px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:10px}.title{font-size:14px;font-weight:760}.body{padding:12px;overflow:auto;max-height:calc(100vh - 116px)}.stack{display:grid;gap:10px}.small{font-size:12px;color:var(--muted)}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
    button{font:inherit;border:1px solid var(--line);background:#fff;color:var(--ink);border-radius:8px;padding:9px 10px;cursor:pointer;text-align:left}button.active{border-color:#75beb4;background:var(--updsoft)}.toolbar{display:flex;gap:8px;align-items:center;margin-bottom:12px}.toolbar button{text-align:center}.row{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}.content{font-size:13px;line-height:1.45;margin-top:7px}.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.chip{display:inline-flex;align-items:center;min-height:22px;padding:3px 7px;border-radius:999px;background:var(--soft);font-size:11px;color:#344054}.chip.new{background:var(--newsoft);color:var(--new)}.chip.upd{background:var(--updsoft);color:var(--upd)}.chip.ign{background:var(--ignsoft);color:var(--ign)}
    .incoming{border:1px solid #a8b5c5;border-left:5px solid var(--hot);border-radius:8px;padding:11px;background:#fffdf7;margin-bottom:13px}.decision{border:1px solid var(--line);border-radius:8px;background:#fbfcfe;padding:10px;margin-bottom:12px}.canvas{min-height:620px;overflow:auto;padding:8px 12px 28px}.memoryTree{display:flex;align-items:flex-start;gap:34px;min-width:980px}.rootColumn{position:sticky;left:0;z-index:2;background:linear-gradient(90deg,#fff 82%,rgba(255,255,255,0));padding-right:10px}.treeRoot{display:flex;align-items:center;justify-content:center;background:var(--root);color:#fff;border-radius:999px;width:120px;height:120px;font-weight:760;text-align:center;line-height:1.25;box-shadow:0 12px 24px rgba(16,36,42,.18)}.threadColumn{display:grid;gap:18px;min-width:0}.threadRow{display:grid;grid-template-columns:minmax(260px,360px) minmax(360px,1fr);gap:34px;align-items:center;position:relative}.threadRow::before{content:"";position:absolute;left:-34px;top:50%;width:34px;border-top:2px solid #9aa8b7}.threadRow::after{content:"";position:absolute;left:360px;top:50%;width:34px;border-top:2px solid #9aa8b7}.leafColumn{display:flex;flex-wrap:wrap;gap:10px;align-items:center}.node{display:inline-block;vertical-align:top;border:1px solid var(--line);border-radius:999px;background:#fff;min-width:230px;max-width:360px;padding:13px 16px;transition:background .2s,border-color .2s,transform .2s}.node.hot{border-color:#f2b540;box-shadow:0 0 0 4px rgba(245,158,11,.16)}.node.new{border-color:#9db9ff;background:#fbfdff}.node.updated{border-color:#75beb4;background:#fbfffe}.node.episode{min-width:170px;max-width:250px;background:#fbfcfe;border-radius:999px}.node.ignored{border-color:#f6c768;background:#fffaf0}.node:hover{transform:translateY(-1px)}.nodeTitle{font-weight:760;font-size:13px}.nodeText{font-size:12px;color:#344054;line-height:1.42;margin-top:6px}.section{border-top:1px solid var(--line);padding-top:12px;margin-top:12px}.section:first-child{border-top:0;padding-top:0;margin-top:0}.empty{border:1px dashed #cbd5e1;border-radius:8px;background:#fbfcfe;color:var(--muted);padding:12px;font-size:13px;line-height:1.45}pre{white-space:pre-wrap;word-break:break-word;background:#0f172a;color:#dbeafe;border-radius:8px;padding:10px;font-size:11px;max-height:260px;overflow:auto}
    @media(max-width:1200px){main{grid-template-columns:300px 1fr}#inspector{grid-column:1/-1}}@media(max-width:760px){header,main{display:block}.panel{margin:12px}.body{max-height:none}.memoryTree{min-width:760px}.treeRoot{width:96px;height:96px}.threadRow{grid-template-columns:230px minmax(300px,1fr)}.threadRow::after{left:230px}.node{min-width:210px}.node.episode{min-width:160px}}
  </style>
</head>
<body>
<header><div><h1>L2 Dynamic Thread Tree</h1><div class="sub">逐筆播放：每一個 L1 node 進來後，L2 topic threads 如何新增或更新</div></div><div class="metrics" id="metrics"></div></header>
<main>
  <aside class="panel"><div class="head"><div class="title">L1 Event Timeline</div><div class="small" id="mode"></div></div><div class="body stack" id="events"></div></aside>
  <section class="panel"><div class="head"><div><div class="title" id="eventTitle">Event</div><div class="small" id="eventSub"></div></div></div><div class="body"><div class="toolbar"><button id="prevBtn">Prev</button><button id="playBtn">Play</button><button id="nextBtn">Next</button><span class="small" id="playState"></span></div><div id="incoming"></div><div class="decision" id="decisionBox"></div><div class="canvas"><div class="memoryTree"><div class="rootColumn"><div class="treeRoot">L2<br>Memory<br>Tree</div></div><div class="threadColumn" id="tree"></div></div></div></div></section>
  <aside class="panel" id="inspector"><div class="head"><div class="title">Inspector</div><div class="small" id="selected"></div></div><div class="body" id="inspectorBody"></div></aside>
</main>
<script>
const state={demo:null,index:0,selected:null,timer:null};
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function load(){const r=await fetch("thread_l2_demo.json");if(!r.ok)throw new Error(`thread_l2_demo.json: ${r.status}`);state.demo=await r.json();render();}
function events(){return state.demo.events&&state.demo.events.length?state.demo.events:legacyEvents();}
function event(){return events()[state.index];}
function legacyEvents(){return (state.demo.steps||[]).map((s,i)=>({event_index:i+1,step_index:s.step_index,meeting_id:s.meeting_id,meeting_date:s.meeting_date,timestamp:s.timestamp,l1_node:(s.new_l1_nodes||[])[0]||{},decision:(s.decisions||[])[0]||{},candidate_threads:[],threads_before:s.threads_before||[],threads_after:s.threads_after||[],created_thread_ids:s.created_thread_ids||[],updated_thread_ids:s.updated_thread_ids||[]}));}
function metric(label,value){return `<div class="metric"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`}
function renderMetrics(){const d=state.demo;const ev=events();$("metrics").innerHTML=[metric("meetings",(d.steps||[]).length),metric("L1 events",ev.length),metric("threads",d.final_threads.length),metric("mode",d.mode)].join("");$("mode").textContent=d.mode;}
function renderEvents(){const ev=events();$("events").innerHTML=ev.map((e,i)=>{const d=e.decision||{};const cls=d.action==="create_thread"?"new":d.action==="attach_thread"?"upd":"ign";return `<button class="${i===state.index?"active":""}" data-i="${i}"><div class="row"><strong>${esc(e.meeting_id)}</strong><span class="small">#${e.event_index}</span></div><div class="small mono">${esc(e.l1_node?.obj_id||"")}</div><div class="chips"><span class="chip">${esc(e.l1_node?.type||"")}</span><span class="chip ${cls}">${esc(d.action||"")}</span>${d.target_thread_id?`<span class="chip upd">${esc(d.target_thread_id)}</span>`:""}</div></button>`}).join("");$("events").querySelectorAll("button").forEach(b=>b.onclick=()=>{state.index=Number(b.dataset.i);state.selected=null;render();});}
function renderMain(){const e=event();const n=e.l1_node||{};const d=e.decision||{};const actionClass=d.action==="create_thread"?"new":d.action==="attach_thread"?"upd":"ign";$("eventTitle").textContent=`Event ${e.event_index}: ${e.meeting_id}`;$("eventSub").textContent=`L1 ${n.obj_id||""} enters memory, then L2 tree updates`;$("incoming").innerHTML=`<div class="incoming" data-kind="l1" data-id="${esc(n.obj_id)}"><div class="row"><strong>Incoming L1</strong><span class="mono small">${esc(n.obj_id)}</span></div><div class="chips"><span class="chip">${esc(n.type)}</span><span class="chip">${esc(n.importance)}</span></div><div class="content">${esc(n.content)}</div></div>`;$("decisionBox").innerHTML=`<div class="row"><strong>Update Decision</strong><span class="chip ${actionClass}">${esc(d.action||"no decision")}</span></div><div class="chips">${d.target_thread_id?`<span class="chip upd">target ${esc(d.target_thread_id)}</span>`:""}${(e.created_thread_ids||[]).map(x=>`<span class="chip new">created ${esc(x)}</span>`).join("")}${(e.updated_thread_ids||[]).map(x=>`<span class="chip upd">updated ${esc(x)}</span>`).join("")}</div><div class="content">${esc(d.reason||"")}</div>`;renderTree();}
function renderTree(){const e=event();const created=new Set(e.created_thread_ids||[]);const updated=new Set(e.updated_thread_ids||[]);const target=e.decision?.target_thread_id||"";const threads=e.threads_after||[];$("tree").innerHTML=threads.map(t=>{const cls=[created.has(t.thread_id)?"new":"",updated.has(t.thread_id)?"updated":"",target===t.thread_id?"hot":""].filter(Boolean).join(" ");const episodes=t.episodes||[];const leaves=episodes.map((ep,idx)=>{const l1ids=ep.source_l1_ids||[];const isHot=l1ids.includes(e.l1_node?.obj_id);return `<div class="node episode ${isHot?"hot":""}" data-kind="episode" data-thread="${esc(t.thread_id)}" data-idx="${idx}"><div class="row"><div class="nodeTitle">${esc(l1ids[0]||ep.meeting_id)}</div><span class="chip">${esc(ep.source_l1_type||ep.change_type)}</span></div><div class="nodeText">${esc(ep.summary)}</div><div class="chips"><span class="chip">${esc(ep.meeting_id)}</span><span class="chip">${esc(ep.change_type)}</span></div></div>`}).join("");return `<div class="threadRow"><div class="node ${cls}" data-kind="thread" data-id="${esc(t.thread_id)}"><div class="row"><div class="nodeTitle">${esc(t.title||"Untitled thread")}</div><span class="mono small">${esc(t.thread_id)}</span></div><div class="nodeText">${esc(t.current_status||"")}</div><div class="chips"><span class="chip">${episodes.length} L1 leaves</span>${created.has(t.thread_id)?`<span class="chip new">new thread</span>`:""}${updated.has(t.thread_id)?`<span class="chip upd">updated</span>`:""}</div></div><div class="leafColumn">${leaves||`<div class="node episode"><div class="nodeTitle">No L1 leaf</div></div>`}</div></div>`}).join("")||`<div class="threadRow"><div class="node ignored hot"><div class="nodeTitle">No L2 thread yet</div><div class="nodeText">This L1 did not create or update a thread.</div></div><div class="leafColumn"></div></div>`;document.querySelectorAll("[data-kind]").forEach(el=>el.onclick=()=>{state.selected={kind:el.dataset.kind,id:el.dataset.id,thread:el.dataset.thread,idx:el.dataset.idx};renderInspector();});}
function renderInspector(){const e=event();if(!state.selected){$("selected").textContent="";$("inspectorBody").innerHTML=`<div class="empty">Click incoming L1, a thread, or an episode node to inspect the exact decision and state.</div>`;return;}$("selected").textContent=state.selected.id||state.selected.thread||"";if(state.selected.kind==="l1"){const n=e.l1_node||{};const d=e.decision||{};$("inspectorBody").innerHTML=`<div class="section"><div class="title">Incoming L1</div><div class="decision"><div class="chips"><span class="chip">${esc(n.type)}</span><span class="chip">${esc(n.importance)}</span></div><div class="content">${esc(n.content)}</div></div></div><div class="section"><div class="title">Applied Decision</div><pre>${esc(JSON.stringify(d,null,2))}</pre></div><div class="section"><div class="title">Candidate Threads</div><pre>${esc(JSON.stringify(e.candidate_threads||[],null,2))}</pre></div>`;return;}if(state.selected.kind==="episode"){const t=(e.threads_after||[]).find(x=>x.thread_id===state.selected.thread);const ep=(t?.episodes||[])[Number(state.selected.idx)];$("inspectorBody").innerHTML=`<div class="section"><div class="title">Episode</div><pre>${esc(JSON.stringify(ep,null,2))}</pre></div><div class="section"><div class="title">Parent Thread</div><pre>${esc(JSON.stringify(t,null,2))}</pre></div>`;return;}const t=(e.threads_after||[]).find(x=>x.thread_id===state.selected.id);$("inspectorBody").innerHTML=`<div class="section"><div class="title">Thread State After Event</div><pre>${esc(JSON.stringify(t,null,2))}</pre></div>`;}
function render(){renderMetrics();renderEvents();renderMain();renderInspector();$("playState").textContent=`${state.index+1}/${events().length}`;}
function next(){state.index=Math.min(events().length-1,state.index+1);state.selected=null;render();}
function prev(){state.index=Math.max(0,state.index-1);state.selected=null;render();}
$("nextBtn").onclick=next;$("prevBtn").onclick=prev;$("playBtn").onclick=()=>{if(state.timer){clearInterval(state.timer);state.timer=null;$("playBtn").textContent="Play";return;}$("playBtn").textContent="Pause";state.timer=setInterval(()=>{if(state.index>=events().length-1){clearInterval(state.timer);state.timer=null;$("playBtn").textContent="Play";return;}next();},1400);};
load().catch(e=>{document.body.innerHTML=`<pre style="margin:20px">${esc(e.stack||e.message)}</pre>`});
</script>
</body>
</html>"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build replayable topic/thread L2 demo artifacts from L1 meetings."
    )
    parser.add_argument("--tree", default="long_term/tree.json")
    parser.add_argument("--meetings", nargs="+", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--heuristic-only",
        action="store_true",
        help="Do not call the LLM; use local similarity heuristics for a fast demo.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tree_path = Path(args.tree).resolve()
    out_dir = Path(args.out_dir).resolve()
    tree = load_tree(tree_path)
    api_keys = None if args.heuristic_only else load_api_keys()
    result = run_thread_l2_demo(
        tree=tree,
        meeting_ids=list(args.meetings),
        out_dir=out_dir,
        model_name=resolve_model_name(args.model),
        api_key=api_keys,
        heuristic_only=bool(args.heuristic_only),
    )
    print(f"Thread L2 demo written: {result.artifact_path}")
    print(f"Viewer written: {result.viewer_path}")


if __name__ == "__main__":
    main()
