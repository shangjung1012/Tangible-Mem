"""Summarize: aggregate L1 meetings into L2 phase summaries, and L2 phases
into the L3 project profile."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from gemini_clients import create_gemini_client
from io_utils import load_api_keys, load_tree, print_json_safe, save_json, utc_now_iso
from l1_quality import (
    format_l1_quality_tag,
    load_l1_quality_index,
    quality_index_default_path,
)
from schema import (
    DEFAULT_MODEL_NAME,
    PHASE_SUMMARY_SCHEMA,
    PROFILE_UPDATE_SCHEMA,
)


# ---------------------------------------------------------------------------
# Shared JSON extraction
# ---------------------------------------------------------------------------

def _extract_json(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        raise RuntimeError("Response does not contain valid JSON object.")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse JSON output.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("JSON output must be an object.")
    return data


# ===================================================================
# L1 → L2  (Phase Summary)
# ===================================================================

def _build_phase_summary_prompt(
    phase_id: str,
    meetings: list[dict[str, Any]],
    quality_index: dict[str, Any] | None = None,
) -> str:
    meetings_text = ""
    for m in meetings:
        meetings_text += f"\n--- Meeting: {m['meeting_id']} ---\n"
        for obj in m.get("memory_objects", []):
            evidence = str(obj.get("evidence", "")).strip()
            if len(evidence) > 220:
                evidence = evidence[:217].rstrip() + "..."
            meetings_text += (
                f"  [{obj.get('obj_id', '?')}] "
                f"type={obj['type']} importance={obj['importance']} "
                f"({format_l1_quality_tag(obj, quality_index)}) "
                f"{obj['content']}\n"
            )
            if evidence:
                meetings_text += f"    evidence={evidence}\n"

    return f"""
你是「長期記憶彙整器」。
任務：將多個會議的 L1 記憶物件彙整成一個階段性摘要（L2 Phase Summary）。

★ 核心原則：每一層只回答自己層次的問題，不要抄寫下層的細節。

品質訊號使用規則：
- quality=strong/normal 的 decision、method_change、result 可以升級成 phase-level changes 或摘要依據。
- quality=tentative 的 L1 只能當背景，除非被多個 L1 或 recurrence 支撐，不要寫成已確立變更。
- quality=weak 的 L1 原則上不要升級到 L2；最多作為背景脈絡。
- quality=unknown 表示舊流程或沒有 sidecar，請回到既有標準，根據 type、importance、content、evidence 判斷。
- open_question 只有在仍阻礙下一步時才放入 open_to_next。
- argument 不要直接升級成 change，只能作為 decision/method_change 的理由背景。

欄位規則：
1) summary：本階段的主軸是什麼？1-2 句，60 字以內。只寫大方向，不要列舉。
2) changes：本階段「淨」的方法變化，最多 5 條。
   - 只寫這段期間確立或棄用的重要做法，不要把每個小調整都列出來
   - 每條 method 限 30 字以內，不要含 reason（reason 留在 L1）
   - status 只有三種：adopted（確立）/ abandoned（棄用）/ evolved（持續演進）
3) open_to_next：本階段結束時仍懸而未決的真正懸案，最多 2 條，每條 40 字以內。
   - 不要把所有 todo 都列入，只保留真正影響下一步進展的問題
4) 回傳 JSON only，文字使用繁體中文。

階段 ID：{phase_id}

本階段包含的會議記憶物件：
{meetings_text}
""".strip()


def summarize_phase(
    model_name: str,
    api_key: str | list[str],
    tree: dict[str, Any],
    phase_id: str,
    time_start: str,
    time_end: str,
    meeting_ids: list[str] | None = None,
    quality_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create or update an L2 phase summary from L1 meetings."""
    client = create_gemini_client(api_key)

    all_meetings: list[dict[str, Any]] = tree.get("meetings", [])

    if meeting_ids:
        id_set = set(meeting_ids)
        meetings = [m for m in all_meetings if m["meeting_id"] in id_set]
    else:
        meetings = [m for m in all_meetings if m.get("phase_id") == phase_id]

    if not meetings:
        raise RuntimeError(
            f"No meetings found for phase {phase_id}. "
            "Use --meetings to specify meeting IDs."
        )

    prompt = _build_phase_summary_prompt(phase_id, meetings, quality_index)
    config = {
        "temperature": 0.15,
        "response_mime_type": "application/json",
        "response_json_schema": PHASE_SUMMARY_SCHEMA,
    }
    response = client.models.generate_content(
        model=model_name, contents=prompt, config=config
    )
    result = _extract_json(response.text or "")

    child_meeting_ids = [m["meeting_id"] for m in meetings]

    phase_node: dict[str, Any] = {
        "phase_id": phase_id,
        "time_range": {"start": time_start, "end": time_end},
        "summary": result.get("summary", ""),
        "changes": result.get("changes", []),
        "open_to_next": result.get("open_to_next", []),
        "child_meeting_ids": child_meeting_ids,
    }

    # Assign meetings to this phase
    meeting_set = set(child_meeting_ids)
    for m in all_meetings:
        if m["meeting_id"] in meeting_set:
            m["phase_id"] = phase_id

    # Upsert phase
    phases: list[dict[str, Any]] = tree.get("phases", [])
    existing_idx: int | None = None
    for i, p in enumerate(phases):
        if p.get("phase_id") == phase_id:
            existing_idx = i
            break
    if existing_idx is not None:
        phases[existing_idx] = phase_node
    else:
        phases.append(phase_node)
    phases.sort(key=lambda p: p.get("phase_id", ""))
    tree["phases"] = phases

    # Update project profile's child_phase_ids
    profile = tree.get("project_profile", {})
    child_ids = set(profile.get("child_phase_ids", []))
    child_ids.add(phase_id)
    profile["child_phase_ids"] = sorted(child_ids)
    tree["project_profile"] = profile

    tree["tree_version"] = int(tree.get("tree_version", 0) or 0) + 1
    tree["last_updated_utc"] = utc_now_iso()

    return phase_node


# ===================================================================
# L2 → L3  (Project Profile)
# ===================================================================

def _build_profile_update_prompt(
    phases: list[dict[str, Any]],
    current_profile: dict[str, Any],
) -> str:
    phases_text = ""
    for p in phases:
        tr = p.get("time_range", {})
        phases_text += (
            f"\n--- Phase: {p['phase_id']} "
            f"({tr.get('start', '?')} ~ {tr.get('end', '?')}) ---\n"
        )
        phases_text += f"  Summary: {p.get('summary', '')}\n"
        for ch in p.get("changes", []):
            phases_text += f"  [{ch.get('status', '?')}] {ch.get('method', '')}\n"
        for issue in p.get("open_to_next", []):
            phases_text += f"  [open] {issue}\n"

    slim_profile = {
        "core_goal": current_profile.get("core_goal", ""),
        "current_phase": current_profile.get("current_phase", ""),
        "established_methods": current_profile.get("established_methods", []),
        "long_term_open_questions": current_profile.get(
            "long_term_open_questions", []
        ),
    }
    current_profile_text = json.dumps(slim_profile, ensure_ascii=False, indent=2)

    return f"""
你是「研究計畫輪廓更新器」。
任務：根據所有階段摘要（L2）更新研究計畫的長期輪廓（L3 Project Profile）。

★ 核心原則：L3 回答的是「整個專案的全局」，不是彙整 L2 的細節。

欄位規則：
1) core_goal：整個專案的核心目標，1-2 句，60 字以內。不要描述方法細節。
2) current_phase：目前整個研究所處的大階段，1 句，30 字以內。
3) established_methods：目前跨越多個 phase 都沒有變動的穩定核心做法，最多 5 條，每條 35 字以內。
   - 只列已確立且仍在使用的做法，不要列已棄用的
   - 不要把某一個 phase 的單次決策列進來
4) long_term_open_questions：從多個 phase 看下來至今仍懸而未決的長期問題，最多 3 條，每條 40 字以內。
   - 只保留真正橫跨多個階段、影響整個研究方向的問題
   - 不要列近期的 todo 或已解決的問題
5) 回傳 JSON only，文字使用繁體中文。

目前的 Project Profile（供更新參考）：
{current_profile_text}

所有階段摘要（按時間順序）：
{phases_text}
""".strip()


def update_project_profile(
    model_name: str,
    api_key: str | list[str],
    tree: dict[str, Any],
    project_id: str = "virtual-mentor",
) -> dict[str, Any]:
    """Update the L3 project profile from all L2 phases."""
    client = create_gemini_client(api_key)

    phases = tree.get("phases", [])
    if not phases:
        raise RuntimeError("No phases found. Run phase summarization first.")

    current_profile = tree.get("project_profile", {})
    prompt = _build_profile_update_prompt(phases, current_profile)
    config = {
        "temperature": 0.15,
        "response_mime_type": "application/json",
        "response_json_schema": PROFILE_UPDATE_SCHEMA,
    }
    response = client.models.generate_content(
        model=model_name, contents=prompt, config=config
    )
    result = _extract_json(response.text or "")

    all_starts = [
        p["time_range"]["start"]
        for p in phases
        if p.get("time_range", {}).get("start")
    ]
    all_ends = [
        p["time_range"]["end"]
        for p in phases
        if p.get("time_range", {}).get("end")
    ]

    profile: dict[str, Any] = {
        "project_id": project_id,
        "time_range": {
            "start": min(all_starts) if all_starts else "",
            "end": max(all_ends) if all_ends else "",
        },
        "core_goal": result.get("core_goal", ""),
        "current_phase": result.get("current_phase", ""),
        "established_methods": result.get("established_methods", []),
        "long_term_open_questions": result.get("long_term_open_questions", []),
        "child_phase_ids": sorted(p["phase_id"] for p in phases),
    }

    tree["project_profile"] = profile
    tree["tree_version"] = int(tree.get("tree_version", 0) or 0) + 1
    tree["last_updated_utc"] = utc_now_iso()

    return profile


# ===================================================================
# CLI
# ===================================================================

def resolve_model_name(requested_model: str | None) -> str:
    clean = str(requested_model or "").strip()
    if clean:
        return clean
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL_NAME)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize L1→L2 phase or L2→L3 project profile."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- phase ---
    phase_p = sub.add_parser("phase", help="Create / update an L2 phase summary.")
    phase_p.add_argument(
        "--phase-id", required=True, help="Phase ID, e.g. P-2026-03."
    )
    phase_p.add_argument(
        "--time-start", required=True, help="Phase start date (YYYY-MM-DD)."
    )
    phase_p.add_argument(
        "--time-end", required=True, help="Phase end date (YYYY-MM-DD)."
    )
    phase_p.add_argument(
        "--meetings", nargs="*", help="Specific meeting IDs to include."
    )
    phase_p.add_argument("--tree", default="long_term/tree.json")
    phase_p.add_argument("--snapshot-dir", default="long_term/snapshots")
    phase_p.add_argument(
        "--model",
        default=None,
        help=(
            "Gemini model name. Defaults to GEMINI_MODEL from .env, "
            f"or {DEFAULT_MODEL_NAME} if unset."
        ),
    )
    phase_p.add_argument("--dry-run", action="store_true")

    # --- profile ---
    prof_p = sub.add_parser("profile", help="Update L3 project profile.")
    prof_p.add_argument("--project-id", default="virtual-mentor")
    prof_p.add_argument("--tree", default="long_term/tree.json")
    prof_p.add_argument("--snapshot-dir", default="long_term/snapshots")
    prof_p.add_argument(
        "--model",
        default=None,
        help=(
            "Gemini model name. Defaults to GEMINI_MODEL from .env, "
            f"or {DEFAULT_MODEL_NAME} if unset."
        ),
    )
    prof_p.add_argument("--dry-run", action="store_true")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tree_path = Path(args.tree).resolve()
    snapshot_dir = Path(args.snapshot_dir).resolve()
    tree = load_tree(tree_path)
    api_keys = load_api_keys()
    model_name = resolve_model_name(args.model)

    if args.command == "phase":
        quality_index = load_l1_quality_index(quality_index_default_path(tree_path))
        phase_node = summarize_phase(
            model_name=model_name,
            api_key=api_keys,
            tree=tree,
            phase_id=args.phase_id,
            time_start=args.time_start,
            time_end=args.time_end,
            meeting_ids=args.meetings,
            quality_index=quality_index,
        )
        if args.dry_run:
            print_json_safe(phase_node)
            return
        save_json(tree_path, tree)
        snap = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_phase_{args.phase_id}.json"
        save_json(snapshot_dir / snap, tree)
        print(f"Phase summary created: {args.phase_id}")
        print(f"Meetings included: {phase_node['child_meeting_ids']}")

    elif args.command == "profile":
        profile = update_project_profile(
            model_name=model_name,
            api_key=api_keys,
            tree=tree,
            project_id=args.project_id,
        )
        if args.dry_run:
            print_json_safe(profile)
            return
        save_json(tree_path, tree)
        snap = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_profile.json"
        save_json(snapshot_dir / snap, tree)
        print(f"Project profile updated: {profile['project_id']}")
        print(f"Established methods: {len(profile.get('established_methods', []))}")
        print(
            f"Open questions: {len(profile.get('long_term_open_questions', []))}"
        )


if __name__ == "__main__":
    main()
