"""End-to-end test: populate long-term memory tree from ICSI transcripts,
then ask questions via recall planner + recall."""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

# ── make long_term/ importable ──
sys.path.insert(0, str(Path(__file__).resolve().parent / "long_term"))

from io_utils import load_env, load_tree, save_json, utc_now_iso  # noqa: E402
from bridge import (  # noqa: E402
    call_gemini_bridge,
    collect_existing_topics,
    insert_meeting_into_tree,
    normalize_memory_objects,
)
from embedder import EmbedCache  # noqa: E402
from recall_planner import plan_recall  # noqa: E402
from recall import recall, format_recall_for_prompt  # noqa: E402


# ===================================================================
# 1. MRT → plain text
# ===================================================================

_SEGMENT_RE = re.compile(
    r'<Segment\s+StartTime="([^"]+)"\s+EndTime="[^"]+"\s+Participant="([^"]+)">'
    r"(.*?)</Segment>",
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def mrt_to_text(mrt_path: Path) -> str:
    """Parse ICSI .mrt XML into plain speaker-turn text."""
    raw = mrt_path.read_text(encoding="iso-8859-1")
    lines: list[str] = []
    for match in _SEGMENT_RE.finditer(raw):
        start_time, speaker, body = match.group(1), match.group(2), match.group(3)
        text = _TAG_RE.sub("", body).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            lines.append(f"[{speaker} @ {start_time}s]: {text}")
    return "\n".join(lines)


# ===================================================================
# 2. Run
# ===================================================================

def main() -> None:
    api_key = load_env()
    tree_path = Path("long_term/tree.json").resolve()
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    embed_model_name = os.getenv("GEMINI_EMBED_MODEL", "models/gemini-embedding-001").strip()
    test_mode_raw = os.getenv("LONG_TERM_TEST_MODE", "all").strip().lower()
    test_mode = test_mode_raw if test_mode_raw in {"all", "bridge", "recall"} else "all"
    bridge_retry_raw = os.getenv("LONG_TERM_BRIDGE_MAX_RETRIES", "6").strip()
    bridge_interval_raw = os.getenv("LONG_TERM_BRIDGE_INTERVAL_S", "0").strip()
    stop_on_error = os.getenv("LONG_TERM_STOP_ON_ERROR", "").strip() == "1"
    resume_mode = os.getenv("LONG_TERM_TEST_RESUME", "").strip() == "1"
    meetings_raw = os.getenv("LONG_TERM_TEST_MEETINGS", "").strip()
    try:
        bridge_max_retries = max(1, int(bridge_retry_raw))
    except ValueError:
        bridge_max_retries = 6
    try:
        bridge_interval_s = max(0.0, float(bridge_interval_raw))
    except ValueError:
        bridge_interval_s = 0.0

    # ── tree initialization ──
    if test_mode == "recall" or resume_mode:
        tree = load_tree(tree_path)
    else:
        from schema import DEFAULT_TREE
        from copy import deepcopy

        tree = deepcopy(DEFAULT_TREE)

    # ── pick 10 transcripts to test ──
    transcript_dir = Path("ICSI_original_transcripts/transcripts").resolve()
    test_files = [
        "Bmr001.mrt", "Bmr002.mrt", "Bmr003.mrt", "Bmr005.mrt", "Bmr006.mrt",
        "Bmr007.mrt", "Bmr008.mrt", "Bmr009.mrt", "Bmr010.mrt", "Bmr011.mrt",
    ]
    if meetings_raw:
        custom_files: list[str] = []
        for token in re.split(r"[,\s]+", meetings_raw):
            t = token.strip()
            if not t:
                continue
            custom_files.append(f"{t}.mrt" if not t.endswith(".mrt") else t)
        if custom_files:
            test_files = custom_files

    limit_raw = os.getenv("LONG_TERM_TEST_LIMIT", "").strip()
    if limit_raw:
        try:
            limit = max(1, int(limit_raw))
            test_files = test_files[:limit]
        except ValueError:
            pass

    requested_ids = [Path(name).stem for name in test_files]
    skipped_existing_ids: list[str] = []
    if resume_mode and test_mode in {"all", "bridge"}:
        existing_ids = {m.get("meeting_id", "") for m in tree.get("meetings", [])}
        skipped_existing_ids = [mid for mid in requested_ids if mid in existing_ids]
        test_files = [name for name in test_files if Path(name).stem not in existing_ids]

    failed_meetings: list[str] = []
    succeeded_meetings: list[str] = []
    missing_transcript_ids: list[str] = []

    # ===== Step 1: Bridge (extract L1 memory objects) =====
    if test_mode in {"all", "bridge"}:
        print("=" * 60)
        print("STEP 1: Bridge — extracting L1 memory objects")
        print(f"Mode: {test_mode}")
        print(f"Model: {model_name}")
        print(f"Embed model: {embed_model_name or '(default)'}")
        print(f"Resume mode: {resume_mode}")
        print(f"Meetings: {len(test_files)}")
        print(f"Bridge retries: {bridge_max_retries} (stop_on_error={stop_on_error})")
        print("=" * 60)

        for filename in test_files:
            mrt_path = transcript_dir / filename
            if not mrt_path.exists():
                print(f"  SKIP: {mrt_path} not found")
                missing_transcript_ids.append(mrt_path.stem)
                continue

            meeting_id = mrt_path.stem
            transcript_text = mrt_to_text(mrt_path)
            # truncate to avoid huge prompts during testing
            if len(transcript_text) > 15000:
                transcript_text = transcript_text[:15000] + "\n... (truncated)"

            print(f"\n  Processing {meeting_id} ({len(transcript_text)} chars)...")
            existing_topics = collect_existing_topics(tree)
            try:
                llm_output = call_gemini_bridge(
                    model_name=model_name,
                    api_key=api_key,
                    transcript=transcript_text,
                    meeting_id=meeting_id,
                    existing_topics=existing_topics,
                    max_retries=bridge_max_retries,
                )

                raw_objects = llm_output.get("memory_objects", [])
                memory_objects = normalize_memory_objects(raw_objects, meeting_id)
                insert_meeting_into_tree(
                    tree, meeting_id, str(mrt_path), utc_now_iso(), memory_objects
                )
                print(f"  ✓ {meeting_id}: {len(memory_objects)} memory objects extracted")
                for obj in memory_objects:
                    print(f"    [{obj['type']}] (imp={obj['importance']}) {obj['content'][:80]}")
                succeeded_meetings.append(meeting_id)
            except Exception as exc:
                print(f"  ✗ {meeting_id}: {type(exc).__name__}: {exc}")
                failed_meetings.append(meeting_id)
                if stop_on_error:
                    save_json(tree_path, tree)
                    raise
            finally:
                # Crash-safe checkpoint after each attempt
                save_json(tree_path, tree)

            if bridge_interval_s > 0:
                time.sleep(bridge_interval_s)

        print(f"\n  Tree saved: {tree_path} (version={tree['tree_version']})")
        print(
            f"  Bridge summary: {len(succeeded_meetings)} succeeded, "
            f"{len(failed_meetings)} failed"
        )
        if failed_meetings:
            print(f"  Failed meetings: {', '.join(failed_meetings)}")

        tree_meeting_ids = {m.get("meeting_id", "") for m in tree.get("meetings", [])}
        pending_ids = [mid for mid in requested_ids if mid not in tree_meeting_ids]
        report = {
            "last_updated_utc": utc_now_iso(),
            "mode": test_mode,
            "resume_mode": resume_mode,
            "requested_ids": requested_ids,
            "skipped_existing_ids": skipped_existing_ids,
            "attempted_ids": [Path(name).stem for name in test_files],
            "succeeded_ids": succeeded_meetings,
            "failed_ids": failed_meetings,
            "missing_transcript_ids": missing_transcript_ids,
            "pending_after_run_ids": pending_ids,
        }
        report_path = Path(
            os.getenv("LONG_TERM_REPORT_PATH", "long_term/bridge_report.json")
        ).resolve()
        save_json(report_path, report)
        print(f"  Bridge report saved: {report_path}")
        if pending_ids:
            print(f"  Pending meetings: {', '.join(pending_ids)}")
        else:
            print("  Pending meetings: none")

        if test_mode == "bridge":
            print("\nBridge-only mode complete. Skip recall step.")
            return
    else:
        print("=" * 60)
        print("STEP 1: Bridge — skipped (recall-only mode)")
        print(f"Mode: {test_mode}")
        print("=" * 60)

    if not tree.get("meetings"):
        print("\nNo meetings were bridged successfully. Skip recall step.")
        return

    # ===== Step 2: Test recall with questions =====
    print("\n" + "=" * 60)
    print("STEP 2: Recall — testing questions")
    print(f"Mode: {test_mode}")
    print("=" * 60)

    test_questions = [
        # Simple question (should route to short_term / L1)
        "目前有哪些待辦事項？",
        # Complex question (should route to long_term, trace method changes)
        "錄音軟體問題的處理過程是什麼？從第一次會議到現在經歷了哪些變化？",
        # Another complex question
        "這幾次會議中，數據收集策略有什麼演進？",
    ]
    shared_cache = EmbedCache()

    for question in test_questions:
        print(f"\n  Q: {question}")
        print("  " + "-" * 50)

        plan = plan_recall(question, api_key, model_name=model_name)
        print(f"  Complexity: {plan['complexity']}")
        print(f"  Targets: {plan['search_targets']}")
        print(f"  Keywords: {plan['keywords']}")

        result = recall(
            query=question,
            plan=plan,
            tree=tree,
            api_key=api_key,
            model_name=model_name,
            embed_cache=shared_cache,
        )

        formatted = format_recall_for_prompt(result)
        print(f"  Long-term hits: {len(result['long_term_results'])}")
        print(f"\n  --- Recall output ---")
        # Print first 500 chars of formatted output
        preview = formatted[:500]
        if len(formatted) > 500:
            preview += "\n  ... (truncated)"
        print(f"  {preview}")

    shared_cache.save()

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
