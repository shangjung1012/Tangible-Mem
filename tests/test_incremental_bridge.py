from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from google.genai import types

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
sys.path.insert(0, str(LONG_TERM_DIR))

from bridge import normalize_memory_objects  # noqa: E402
from gemini_incremental_extractor import (  # noqa: E402
    auto_max_tool_rounds,
    build_function_response_part,
    next_forward_span,
    resolve_max_tool_rounds,
    should_stop,
    update_forward_progress,
)
from incremental_store import (  # noqa: E402
    count_issue_episodes,
    get_max_line_id,
    load_issue_mentions,
    load_issues,
    load_l1_objects,
    read_transcript_span,
    record_issue_mention,
    save_l1_object,
    seed_transcript_lines,
    upsert_issue,
)


class IncrementalBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "incremental.db"
        self.transcript_id = "Unit001"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_transcript_span_reading(self) -> None:
        count = seed_transcript_lines(
            self.db_path,
            self.transcript_id,
            "Teacher: We should change the plan.\n"
            "[Student @ 12.5s]: I can run the experiment.\n"
            "Unattributed closing line.",
        )

        span = read_transcript_span(
            self.db_path,
            self.transcript_id,
            start_line=1,
            end_line=2,
            purpose="forward_scan",
        )

        self.assertEqual(count, 3)
        self.assertEqual(get_max_line_id(self.db_path, self.transcript_id), 3)
        self.assertEqual(span["start_line"], 1)
        self.assertEqual(span["end_line"], 2)
        self.assertEqual(span["lines"][0]["speaker"], "Teacher")
        self.assertEqual(span["lines"][1]["timestamp_sec"], 12.5)
        self.assertIn("2: [Student @ 12.5s] I can run the experiment.", span["formatted_text"])

    def test_issue_update_and_mentions(self) -> None:
        seed_transcript_lines(
            self.db_path,
            self.transcript_id,
            "A: Decide on the baseline.\nB: Baseline is not ready yet.",
        )

        issue = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="Baseline decision",
            status="open",
            importance=0.7,
            summary="The baseline still needs a decision.",
        )
        mention_id = record_issue_mention(
            self.db_path,
            self.transcript_id,
            issue["issue_id"],
            line_id=2,
            purpose="forward_scan",
            note="supporting evidence",
        )
        duplicate_mention_id = record_issue_mention(
            self.db_path,
            self.transcript_id,
            issue["issue_id"],
            line_id=2,
            purpose="forward_scan",
            note="duplicate evidence",
        )

        issues = load_issues(self.db_path, self.transcript_id)
        mentions = load_issue_mentions(self.db_path, self.transcript_id)

        self.assertGreater(mention_id, 0)
        self.assertEqual(duplicate_mention_id, mention_id)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["importance"], 0.7)
        self.assertEqual(issues[0]["mention_count"], 1)
        self.assertEqual(issues[0]["episode_count"], 1)
        self.assertEqual(len(mentions), 1)
        self.assertEqual(mentions[0]["line_id"], 2)
        self.assertEqual(mentions[0]["purpose"], "forward_scan")

    def test_issue_identity_reuses_same_issue_key(self) -> None:
        first = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="RAG temporal problem",
            issue_key="rag_temporal_retrieval",
            status="open",
            importance=0.5,
            summary="Recall retrieves stale context.",
        )
        second = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="Recall gets outdated context",
            issue_key="rag_temporal_retrieval",
            status="open",
            importance=0.6,
            summary="Temporal retrieval needs meeting dates.",
        )
        issues = load_issues(self.db_path, self.transcript_id)

        self.assertEqual(first["issue_id"], second["issue_id"])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["issue_key"], "rag_temporal_retrieval")
        self.assertEqual(issues[0]["title"], "Recall gets outdated context")

    def test_issue_identity_merges_similar_title_and_summary(self) -> None:
        first = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="RAG temporal retrieval problem",
            status="open",
            importance=0.5,
            summary="Recall retrieves outdated context without meeting date.",
        )
        second = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="Temporal retrieval problem in RAG",
            status="open",
            importance=0.6,
            summary="Meeting date is missing so recall returns outdated context.",
        )
        issues = load_issues(self.db_path, self.transcript_id)

        self.assertEqual(first["issue_id"], second["issue_id"])
        self.assertEqual(len(issues), 1)

    def test_issue_identity_keeps_different_issues_separate(self) -> None:
        upsert_issue(
            self.db_path,
            self.transcript_id,
            title="Audio gain clipping",
            status="open",
            importance=0.5,
            summary="The microphone gain clips recorded audio.",
        )
        upsert_issue(
            self.db_path,
            self.transcript_id,
            title="Participant consent form deadline",
            status="open",
            importance=0.5,
            summary="Consent forms must be collected before recording.",
        )
        issues = load_issues(self.db_path, self.transcript_id)

        self.assertEqual(len(issues), 2)

    def test_episode_count_groups_nearby_mentions(self) -> None:
        self.assertEqual(count_issue_episodes([10, 11, 12, 13]), 1)
        self.assertEqual(count_issue_episodes([10, 11, 20, 21, 40]), 3)

    def test_consecutive_issue_mentions_do_not_raise_importance_as_recurrence(self) -> None:
        issue = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="Repeated temporal retrieval problem",
            status="open",
            importance=0.2,
            summary="Temporal retrieval keeps coming up.",
        )

        for line_id in range(1, 6):
            record_issue_mention(
                self.db_path,
                self.transcript_id,
                issue["issue_id"],
                line_id=line_id,
                purpose="forward_scan",
            )

        issues = load_issues(self.db_path, self.transcript_id)

        self.assertEqual(issues[0]["mention_count"], 5)
        self.assertEqual(issues[0]["episode_count"], 1)
        self.assertEqual(issues[0]["importance"], 0.52)

    def test_separated_issue_episodes_raise_importance_floor(self) -> None:
        issue = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="Repeated temporal retrieval problem",
            status="open",
            importance=0.2,
            summary="Temporal retrieval keeps coming up.",
        )

        for line_id in [10, 11, 20, 21, 40]:
            record_issue_mention(
                self.db_path,
                self.transcript_id,
                issue["issue_id"],
                line_id=line_id,
                purpose="forward_scan",
            )

        issues = load_issues(self.db_path, self.transcript_id)

        self.assertEqual(issues[0]["mention_count"], 5)
        self.assertEqual(issues[0]["episode_count"], 3)
        self.assertEqual(issues[0]["importance"], 0.76)

    def test_l1_object_creation_reuses_existing_normalizer(self) -> None:
        raw_object = {
            "type": "todo",
            "content": "Run the next transcription experiment",
            "importance": 0.6,
            "evidence": "I can run the experiment.",
            "related_topics": ["transcription", "experiment"],
        }

        save_l1_object(self.db_path, self.transcript_id, raw_object)
        loaded = load_l1_objects(self.db_path, self.transcript_id)
        normalized = normalize_memory_objects(loaded, self.transcript_id)

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["obj_id"], "L1-Unit001-001")
        self.assertEqual(normalized[0]["type"], "todo")
        self.assertTrue(normalized[0]["content"].startswith("待辦："))
        self.assertEqual(normalized[0]["related_topics"], ["transcription", "experiment"])

    def test_l1_importance_uses_shared_calibration(self) -> None:
        raw_objects = [
            {
                "type": "method_change",
                "content": "這會影響後續方法與實驗設計",
                "importance": 0.36,
                "evidence": "This changes the next step of the pipeline.",
                "related_topics": ["pipeline"],
            },
            {
                "type": "result",
                "content": "午餐閒聊",
                "importance": 0.2,
                "evidence": "",
                "related_topics": [],
            },
        ]

        normalized = normalize_memory_objects(raw_objects, self.transcript_id)

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["type"], "method_change")
        self.assertGreaterEqual(normalized[0]["importance"], 0.5)

    def test_incremental_stop_condition_helpers(self) -> None:
        self.assertEqual(next_forward_span(0, 5, 2), (1, 2))
        self.assertFalse(should_stop(2, 5))

        progress = update_forward_progress(
            2,
            purpose="lookback",
            end_line=4,
            max_line=5,
        )
        self.assertEqual(progress, 2)

        progress = update_forward_progress(
            2,
            purpose="forward_scan",
            end_line=5,
            max_line=5,
        )
        self.assertTrue(should_stop(progress, 5))

    def test_auto_tool_rounds_scales_with_transcript_length(self) -> None:
        self.assertEqual(auto_max_tool_rounds(5746, 40), 596)

        resolved, is_auto = resolve_max_tool_rounds(
            0,
            max_line=5746,
            chunk_size=40,
        )
        self.assertTrue(is_auto)
        self.assertEqual(resolved, 596)

        resolved, is_auto = resolve_max_tool_rounds(
            80,
            max_line=5746,
            chunk_size=40,
        )
        self.assertFalse(is_auto)
        self.assertEqual(resolved, 80)

    def test_function_response_preserves_call_id(self) -> None:
        function_call = types.FunctionCall(
            id="call-123",
            name="read_transcript",
            args={"start_line": 1, "end_line": 2, "purpose": "forward_scan"},
        )

        part = build_function_response_part(
            function_call,
            {"output": {"ok": True}},
        )

        self.assertIsNotNone(part.function_response)
        assert part.function_response is not None
        self.assertEqual(part.function_response.id, "call-123")
        self.assertEqual(part.function_response.name, "read_transcript")


if __name__ == "__main__":
    unittest.main()
