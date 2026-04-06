"""End-to-end test: populate long-term memory tree from ICSI transcripts,
then ask questions via recall planner + recall."""

from __future__ import annotations

import json
import re
import sys
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

    # ── reset tree for clean test ──
    from schema import DEFAULT_TREE
    from copy import deepcopy

    tree = deepcopy(DEFAULT_TREE)

    # ── pick 10 transcripts to test ──
    transcript_dir = Path("ICSI_original_transcripts/transcripts").resolve()
    test_files = [
        "Bmr001.mrt", "Bmr002.mrt", "Bmr003.mrt", "Bmr005.mrt", "Bmr006.mrt",
        "Bmr007.mrt", "Bmr008.mrt", "Bmr009.mrt", "Bmr010.mrt", "Bmr011.mrt",
    ]

    # ===== Step 1: Bridge (extract L1 memory objects) =====
    print("=" * 60)
    print("STEP 1: Bridge — extracting L1 memory objects")
    print("=" * 60)

    for filename in test_files:
        mrt_path = transcript_dir / filename
        if not mrt_path.exists():
            print(f"  SKIP: {mrt_path} not found")
            continue

        meeting_id = mrt_path.stem
        transcript_text = mrt_to_text(mrt_path)
        # truncate to avoid huge prompts during testing
        if len(transcript_text) > 15000:
            transcript_text = transcript_text[:15000] + "\n... (truncated)"

        print(f"\n  Processing {meeting_id} ({len(transcript_text)} chars)...")
        existing_topics = collect_existing_topics(tree)

        llm_output = call_gemini_bridge(
            model_name="gemini-2.5-flash",
            api_key=api_key,
            transcript=transcript_text,
            meeting_id=meeting_id,
            existing_topics=existing_topics,
        )

        raw_objects = llm_output.get("memory_objects", [])
        memory_objects = normalize_memory_objects(raw_objects, meeting_id)
        insert_meeting_into_tree(
            tree, meeting_id, str(mrt_path), utc_now_iso(), memory_objects
        )
        print(f"  ✓ {meeting_id}: {len(memory_objects)} memory objects extracted")
        for obj in memory_objects:
            print(f"    [{obj['type']}] (imp={obj['importance']}) {obj['content'][:80]}")

    # Save tree after bridge
    save_json(tree_path, tree)
    print(f"\n  Tree saved: {tree_path} (version={tree['tree_version']})")

    # ===== Step 2: Test recall with questions =====
    print("\n" + "=" * 60)
    print("STEP 2: Recall — testing questions")
    print("=" * 60)

    test_questions = [
        # Simple question (should route to short_term / L1)
        "目前有哪些待辦事項？",
        # Complex question (should route to long_term, trace method changes)
        "錄音軟體問題的處理過程是什麼？從第一次會議到現在經歷了哪些變化？",
        # Another complex question
        "這幾次會議中，數據收集策略有什麼演進？",
    ]

    for question in test_questions:
        print(f"\n  Q: {question}")
        print("  " + "-" * 50)

        plan = plan_recall(question, api_key)
        print(f"  Complexity: {plan['complexity']}")
        print(f"  Targets: {plan['search_targets']}")
        print(f"  Keywords: {plan['keywords']}")

        result = recall(
            query=question,
            plan=plan,
            tree=tree,
            api_key=api_key,
        )

        formatted = format_recall_for_prompt(result)
        print(f"  Long-term hits: {len(result['long_term_results'])}")
        print(f"\n  --- Recall output ---")
        # Print first 500 chars of formatted output
        preview = formatted[:500]
        if len(formatted) > 500:
            preview += "\n  ... (truncated)"
        print(f"  {preview}")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
