from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from google.genai import types

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
LEGACY_LONG_TERM_DIR = LONG_TERM_DIR / "archive" / "legacy_temporal_l2_l3"
sys.path.insert(0, str(LONG_TERM_DIR))
sys.path.insert(0, str(LEGACY_LONG_TERM_DIR))

from dataset_profiles import (  # noqa: E402
    infer_dataset_profile_name,
    resolve_incremental_settings,
)
from bridge import (  # noqa: E402
    apply_incremental_final_importance_caps,
    normalize_memory_objects,
    propagate_issue_importance_to_raw_objects,
    review_incremental_candidates,
)
from gemini_incremental_extractor import (  # noqa: E402
    ReadSpanRecord,
    ToolLoopState,
    _build_finalization_prompt,
    _build_initial_prompt,
    _bound_line_ids_to_recent_span,
    _compact_issue_line_ids,
    _execute_tool_call,
    _extract_retry_delay_seconds,
    _is_retryable_error,
    _infer_issue_purpose,
    _max_retry_attempts_for_key_count,
    _min_request_interval_for_key_count,
    _post_tool_round_action,
    _sanitize_issue_id_ref,
    auto_max_tool_rounds,
    build_function_response_part,
    next_forward_span,
    resolve_max_tool_rounds,
    should_stop,
    update_forward_progress,
)
from importance import calibrate_issue_importance  # noqa: E402
from incremental_store import (  # noqa: E402
    count_issue_episodes,
    get_max_line_id,
    load_issue_mentions,
    load_issues,
    load_l1_objects,
    read_transcript_span,
    record_issue_mention,
    resolve_issue_reference,
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

    def test_issue_reference_resolves_issue_key_to_canonical_issue_id(self) -> None:
        issue = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="Transcription specification development",
            issue_key="transcription_specification_development",
            status="open",
            importance=0.7,
            summary="Need one durable transcription specification.",
        )

        resolved = resolve_issue_reference(
            self.db_path,
            self.transcript_id,
            issue_ref="transcription_specification_development",
        )

        self.assertEqual(resolved["issue_id"], issue["issue_id"])
        self.assertEqual(resolved["issue_key"], "transcription_specification_development")

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

    def test_issue_identity_does_not_merge_opposite_direction(self) -> None:
        first = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="繼續使用方案 A",
            status="open",
            importance=0.6,
            summary="團隊決定沿用方案 A 作為目前做法。",
        )
        second = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="放棄方案 A",
            status="open",
            importance=0.6,
            summary="團隊決定停用方案 A，改採其他方向。",
        )
        issues = load_issues(self.db_path, self.transcript_id)

        self.assertNotEqual(first["issue_id"], second["issue_id"])
        self.assertEqual(len(issues), 2)

    def test_issue_identity_can_use_semantic_similarity_for_ambiguous_match(self) -> None:
        first = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="錄音雜訊問題",
            status="open",
            importance=0.5,
            summary="錄音時出現穩定的麥克風噪音。",
        )
        with patch("incremental_store._semantic_issue_similarity", return_value=0.91):
            second = upsert_issue(
                self.db_path,
                self.transcript_id,
                title="麥克風噪聲影響錄音品質",
                status="open",
                importance=0.5,
                summary="同一個持續性的錄音噪音問題仍未解決。",
                api_key="test-key",
                embed_cache=object(),
            )

        issues = load_issues(self.db_path, self.transcript_id)
        self.assertEqual(first["issue_id"], second["issue_id"])
        self.assertEqual(len(issues), 1)

    def test_episode_count_groups_nearby_mentions(self) -> None:
        self.assertEqual(count_issue_episodes([10, 11, 12, 13]), 1)
        self.assertEqual(count_issue_episodes([10, 11, 20, 21, 40]), 2)
        self.assertEqual(count_issue_episodes([10, 11, 30, 31, 60]), 3)

    def test_dataset_profiles_infer_isci_and_grace_defaults(self) -> None:
        self.assertEqual(
            infer_dataset_profile_name(
                "meeting_recording/transcript/ISCI/Bdb001.txt"
            ),
            "isci",
        )
        self.assertEqual(
            infer_dataset_profile_name(
                "meeting_recording/transcript/grace/0422.txt"
            ),
            "grace",
        )

        isci_settings = resolve_incremental_settings(
            "meeting_recording/transcript/ISCI/Bdb001.txt"
        )
        grace_settings = resolve_incremental_settings(
            "meeting_recording/transcript/grace/0422.txt"
        )

        self.assertEqual(isci_settings["profile"].name, "isci")
        self.assertEqual(isci_settings["chunk_size"], 40)
        self.assertEqual(isci_settings["issue_episode_gap_lines"], 15)
        self.assertEqual(grace_settings["profile"].name, "grace")
        self.assertEqual(grace_settings["chunk_size"], 24)
        self.assertEqual(grace_settings["issue_episode_gap_lines"], 10)

    def test_cli_overrides_dataset_profile_defaults(self) -> None:
        settings = resolve_incremental_settings(
            "meeting_recording/transcript/grace/0422.txt",
            requested_profile="grace",
            chunk_size=30,
            issue_episode_gap_lines=7,
        )

        self.assertEqual(settings["profile"].name, "grace")
        self.assertEqual(settings["chunk_size"], 30)
        self.assertEqual(settings["chunk_size_source"], "cli")
        self.assertEqual(settings["issue_episode_gap_lines"], 7)
        self.assertEqual(settings["issue_episode_gap_lines_source"], "cli")

    def test_timeout_errors_are_retryable(self) -> None:
        self.assertTrue(_is_retryable_error(RuntimeError("httpx.ReadTimeout: timed out")))
        self.assertTrue(_is_retryable_error(RuntimeError("The read operation timed out")))

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

        for line_id in [10, 11, 30, 31, 60]:
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

    def test_custom_issue_episode_gap_lines_affect_recurrence(self) -> None:
        issue = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="Grace recurring concern",
            status="open",
            importance=0.2,
            summary="A long-turn dataset issue comes back in separated lines.",
            issue_episode_gap_lines=10,
        )

        for line_id in [1, 12, 23]:
            record_issue_mention(
                self.db_path,
                self.transcript_id,
                issue["issue_id"],
                line_id=line_id,
                purpose="forward_scan",
                issue_episode_gap_lines=10,
            )

        issues = load_issues(
            self.db_path,
            self.transcript_id,
            issue_episode_gap_lines=10,
        )

        self.assertEqual(issues[0]["episode_count"], 3)
        self.assertEqual(issues[0]["importance"], 0.76)

    def test_generic_agenda_issue_importance_is_capped(self) -> None:
        issue = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="週三會議議程",
            status="open",
            importance=0.9,
            summary="週三會議的固定議程與流程安排。",
        )
        for line_id in [10, 30, 50, 70]:
            record_issue_mention(
                self.db_path,
                self.transcript_id,
                issue["issue_id"],
                line_id=line_id,
                purpose="forward_scan",
            )

        issues = load_issues(self.db_path, self.transcript_id)

        self.assertEqual(issues[0]["episode_count"], 4)
        self.assertEqual(issues[0]["importance"], 0.6)

    def test_social_issue_importance_is_capped(self) -> None:
        issue = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="提拉米蘇品嚐比賽與燒烤活動",
            status="open",
            importance=0.9,
            summary="週末將舉辦提拉米蘇盲測與燒烤活動。",
        )

        issues = load_issues(self.db_path, self.transcript_id)

        self.assertEqual(issue["issue_id"], issues[0]["issue_id"])
        self.assertEqual(issues[0]["importance"], 0.5)

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

    def test_save_l1_object_resolves_issue_key_reference(self) -> None:
        issue = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="Transcription specification development",
            issue_key="transcription_specification_development",
            status="open",
            importance=0.7,
            summary="Need one durable transcription specification.",
        )
        raw_object = {
            "type": "method_change",
            "content": "建立一份整體轉錄規格。",
            "importance": 0.72,
            "evidence": "We need a transcription specification.",
            "related_topics": ["transcription"],
        }

        save_l1_object(
            self.db_path,
            self.transcript_id,
            raw_object,
            issue_id="transcription_specification_development",
        )
        loaded = load_l1_objects(
            self.db_path,
            self.transcript_id,
            include_issue_metadata=True,
        )

        self.assertEqual(loaded[0]["_issue_id"], issue["issue_id"])

    def test_linked_high_importance_issue_boosts_raw_l1_before_normalization(self) -> None:
        issue = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="Recurring temporal retrieval problem",
            status="open",
            importance=0.5,
            summary="Temporal retrieval returns outdated context.",
        )
        for line_id in [10, 30, 50, 70]:
            record_issue_mention(
                self.db_path,
                self.transcript_id,
                issue["issue_id"],
                line_id=line_id,
                purpose="forward_scan",
            )

        raw_object = {
            "type": "decision",
            "content": "Add temporal anchors to retrieval.",
            "importance": 0.5,
            "evidence": "Retrieval needs meeting dates.",
            "related_topics": ["retrieval"],
        }
        save_l1_object(
            self.db_path,
            self.transcript_id,
            raw_object,
            issue_id=issue["issue_id"],
        )

        default_loaded = load_l1_objects(self.db_path, self.transcript_id)
        loaded_with_link = load_l1_objects(
            self.db_path,
            self.transcript_id,
            include_issue_metadata=True,
        )
        issues = load_issues(self.db_path, self.transcript_id)
        adjusted = propagate_issue_importance_to_raw_objects(loaded_with_link, issues)
        normalized = normalize_memory_objects(adjusted, self.transcript_id)

        self.assertNotIn("_issue_id", default_loaded[0])
        self.assertEqual(loaded_with_link[0]["_issue_id"], issue["issue_id"])
        self.assertEqual(issues[0]["episode_count"], 4)
        self.assertEqual(issues[0]["importance"], 0.85)
        self.assertEqual(adjusted[0]["importance"], 0.54)
        self.assertGreaterEqual(normalized[0]["importance"], 0.56)
        self.assertNotIn("_issue_id", normalized[0])

    def test_candidate_review_dedupes_near_identical_objects(self) -> None:
        raw_objects = [
            {
                "type": "decision",
                "content": "Add meeting dates to retrieval memory.",
                "importance": 0.55,
                "evidence": "We agreed to add meeting dates to retrieval memory.",
                "related_topics": ["retrieval"],
            },
            {
                "type": "decision",
                "content": "Add meeting dates to retrieval memory.",
                "importance": 0.62,
                "evidence": "We agreed to add meeting dates to retrieval memory for stale-context fixes.",
                "related_topics": ["temporal"],
            },
        ]

        reviewed, stats = review_incremental_candidates(raw_objects, issues=[])

        self.assertEqual(stats["input"], 2)
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(stats["dropped_duplicate"], 1)
        self.assertEqual(stats["dropped_weak"], 0)
        self.assertEqual(len(reviewed), 1)
        self.assertEqual(reviewed[0]["importance"], 0.62)
        self.assertEqual(reviewed[0]["related_topics"], ["temporal", "retrieval"])
        self.assertIn("stale-context", reviewed[0]["evidence"])
        self.assertIn("_candidate_review", reviewed[0])

    def test_candidate_review_drops_weak_unlinked_speculative_object(self) -> None:
        raw_objects = [
            {
                "type": "argument",
                "content": "Maybe this concern is not important.",
                "importance": 0.5,
                "evidence": "",
                "related_topics": [],
            }
        ]

        reviewed, stats = review_incremental_candidates(raw_objects, issues=[])

        self.assertEqual(reviewed, [])
        self.assertEqual(stats["input"], 1)
        self.assertEqual(stats["kept"], 0)
        self.assertEqual(stats["dropped_duplicate"], 0)
        self.assertEqual(stats["dropped_weak"], 1)

    def test_candidate_review_rewards_issue_aligned_object(self) -> None:
        issue = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="Temporal retrieval returns outdated context",
            status="open",
            importance=0.5,
            summary="Meeting dates are missing from retrieval context.",
        )
        raw_objects = [
            {
                "type": "decision",
                "content": "Add meeting dates to retrieval context.",
                "importance": 0.5,
                "evidence": "Retrieval returns outdated context without dates.",
                "related_topics": ["retrieval"],
                "_issue_id": issue["issue_id"],
            }
        ]

        issues = load_issues(self.db_path, self.transcript_id)
        reviewed, stats = review_incremental_candidates(raw_objects, issues)

        self.assertEqual(stats["kept"], 1)
        self.assertGreater(reviewed[0]["_candidate_review"]["issue_overlap"], 0.12)
        self.assertIn("issue_aligned:+0.03", reviewed[0]["_candidate_review"]["adjustments"])
        self.assertEqual(reviewed[0]["importance"], 0.53)

    def test_candidate_review_merges_same_issue_checklist_fragments(self) -> None:
        issue = upsert_issue(
            self.db_path,
            self.transcript_id,
            title="Transcription specification development",
            issue_key="transcription_specification_development",
            status="open",
            importance=0.8,
            summary="Need one durable transcription specification.",
        )
        raw_objects = [
            {
                "type": "method_change",
                "content": "需要建立一份完整的轉錄規格，從 NIST spec 出發整理 speaker、channel、metadata 欄位。",
                "importance": 0.88,
                "evidence": "We need a transcription specification.",
                "related_topics": ["transcription"],
                "_issue_id": issue["issue_id"],
            },
            {
                "type": "method_change",
                "content": "轉錄規格需要包含：audio file name, audio file path, audio file format, audio file size, audio file duration, sample rate, bit depth, channel mapping, speaker, participant, microphone, transmission, notes, comments。",
                "importance": 0.9,
                "evidence": "The transcription specification needs to include audio metadata.",
                "related_topics": ["metadata"],
                "_issue_id": issue["issue_id"],
            },
        ]

        reviewed, stats = review_incremental_candidates(raw_objects, load_issues(self.db_path, self.transcript_id))

        self.assertEqual(stats["kept"], 1)
        self.assertEqual(stats["dropped_duplicate"], 1)
        self.assertIn("merged_same_issue:+0.00", reviewed[0]["_candidate_review"]["adjustments"])
        self.assertIn("建立一份完整的轉錄規格", reviewed[0]["content"])

    def test_candidate_review_caps_speculative_importance(self) -> None:
        raw_objects = [
            {
                "type": "open_question",
                "content": "是否需要額外磁碟空間仍然是未解問題。",
                "importance": 0.99,
                "evidence": "Do we have enough disk space?",
                "related_topics": ["storage"],
            }
        ]

        reviewed, _ = review_incremental_candidates(raw_objects, issues=[])

        self.assertEqual(reviewed[0]["importance"], 0.85)
        self.assertIn("type_cap:0.85", reviewed[0]["_candidate_review"]["adjustments"])

    def test_candidate_review_caps_low_value_social_result(self) -> None:
        raw_objects = [
            {
                "type": "result",
                "content": "週末將舉辦提拉米蘇品嚐比賽並搭配燒烤活動。",
                "importance": 0.62,
                "evidence": "There will be a tiramisu tasting and barbecue this weekend.",
                "related_topics": ["social"],
            }
        ]

        reviewed, stats = review_incremental_candidates(raw_objects, issues=[])

        self.assertEqual(len(reviewed), 1)
        self.assertEqual(stats["dropped_weak"], 0)
        self.assertEqual(reviewed[0]["importance"], 0.44)

    def test_candidate_review_caps_low_value_logistics_result(self) -> None:
        raw_objects = [
            {
                "type": "result",
                "content": "已訂購更舒適的耳機，離開時記得關閉麥克風。",
                "importance": 0.58,
                "evidence": "They already ordered more comfortable headsets and reminded everyone to turn off the microphones.",
                "related_topics": ["setup"],
            }
        ]

        reviewed, stats = review_incremental_candidates(raw_objects, issues=[])

        self.assertEqual(len(reviewed), 1)
        self.assertEqual(stats["dropped_weak"], 0)
        self.assertEqual(reviewed[0]["importance"], 0.4)

    def test_candidate_review_caps_low_value_procedural_method_change(self) -> None:
        raw_objects = [
            {
                "type": "method_change",
                "content": "提供錄音操作指示，強調按黑色方塊停止錄音以免清除資料。",
                "importance": 0.82,
                "evidence": "Hit the black square when you're done, but don't hit record again or it will erase everything.",
                "related_topics": ["錄音", "操作說明"],
            }
        ]

        reviewed, stats = review_incremental_candidates(raw_objects, issues=[])

        self.assertEqual(len(reviewed), 1)
        self.assertEqual(stats["dropped_weak"], 0)
        self.assertEqual(reviewed[0]["importance"], 0.55)
        self.assertIn("low_value_cap:0.55", reviewed[0]["_candidate_review"]["adjustments"])

    def test_candidate_review_caps_short_evidence_method_change(self) -> None:
        raw_objects = [
            {
                "type": "method_change",
                "content": "討論了將「意圖」一詞替換為「目標」的術語精煉。",
                "importance": 0.82,
                "evidence": "That's right. Uh.",
                "related_topics": [],
            }
        ]

        reviewed, stats = review_incremental_candidates(raw_objects, issues=[])

        self.assertEqual(len(reviewed), 1)
        self.assertEqual(stats["dropped_weak"], 0)
        self.assertEqual(reviewed[0]["importance"], 0.55)
        self.assertIn("weak_evidence_cap:0.55", reviewed[0]["_candidate_review"]["adjustments"])

    def test_candidate_review_caps_low_value_meeting_move_result(self) -> None:
        raw_objects = [
            {
                "type": "result",
                "content": "會議地點已變更，且Nancy可能無法出席。",
                "importance": 0.8,
                "evidence": "I was looking for you downstairs. I didn't know you had moved the meeting. Nancy probably won't show up.",
                "related_topics": ["會議", "出席"],
            }
        ]

        reviewed, stats = review_incremental_candidates(raw_objects, issues=[])

        self.assertEqual(len(reviewed), 1)
        self.assertEqual(stats["dropped_weak"], 0)
        self.assertEqual(reviewed[0]["importance"], 0.55)
        self.assertIn("low_value_cap:0.55", reviewed[0]["_candidate_review"]["adjustments"])

    def test_candidate_review_drops_very_low_value_digit_reading_result(self) -> None:
        raw_objects = [
            {
                "type": "result",
                "content": "會議中進行了數字轉錄朗讀環節。",
                "importance": 0.44,
                "evidence": "Why don't we do the digits and then turn the mikes off.",
                "related_topics": ["Digit Transcription", "Meeting Procedure"],
            }
        ]

        reviewed, stats = review_incremental_candidates(raw_objects, issues=[])

        self.assertEqual(reviewed, [])
        self.assertEqual(stats["dropped_weak"], 1)

    def test_issue_line_compaction_and_purpose_inference(self) -> None:
        compacted = _compact_issue_line_ids(list(range(10, 40)))
        self.assertLessEqual(len(compacted), 8)
        self.assertEqual(compacted[0], 10)
        self.assertEqual(compacted[-1], 39)

        purpose = _infer_issue_purpose(
            explicit_purpose="",
            line_ids=[105, 110],
            recent_reads=[
                ReadSpanRecord(purpose="forward_scan", start_line=101, end_line=120),
                ReadSpanRecord(purpose="lookback", start_line=80, end_line=100),
            ],
        )
        self.assertEqual(purpose, "forward_scan")

    def test_line_ids_are_bounded_to_recent_span(self) -> None:
        bounded = _bound_line_ids_to_recent_span(
            [105, 130, 999],
            recent_reads=[
                ReadSpanRecord(purpose="lookback", start_line=80, end_line=100),
                ReadSpanRecord(purpose="forward_scan", start_line=101, end_line=120),
            ],
            explicit_purpose="forward_scan",
        )
        self.assertEqual(bounded, [105, 120])

    def test_sanitize_issue_id_ref_rejects_raw_object_ids(self) -> None:
        self.assertEqual(_sanitize_issue_id_ref("RAW-Unit001-abc123"), "")
        self.assertEqual(_sanitize_issue_id_ref("L1-Unit001-001"), "")
        self.assertEqual(_sanitize_issue_id_ref("ISS-Unit001-abc123"), "ISS-Unit001-abc123")

    def test_single_key_request_interval_defaults_to_free_tier_safe_value(self) -> None:
        self.assertEqual(_min_request_interval_for_key_count(1), 12.5)
        self.assertEqual(_min_request_interval_for_key_count(2), 0.0)

    def test_single_key_mode_uses_higher_retry_budget(self) -> None:
        self.assertEqual(_max_retry_attempts_for_key_count(1), 30)
        self.assertEqual(_max_retry_attempts_for_key_count(2), 4)

    def test_single_key_initial_prompt_mentions_request_budgeting(self) -> None:
        prompt = _build_initial_prompt(
            "Unit001",
            120,
            40,
            request_constrained=True,
        )
        self.assertIn("Use as few model turns as possible", prompt)
        self.assertIn("next forward_scan span", prompt)

    def test_retry_delay_parsing_from_quota_error_text(self) -> None:
        exc = RuntimeError("429 RESOURCE_EXHAUSTED. Please retry in 1.260354859s.")
        self.assertEqual(_extract_retry_delay_seconds(exc), 1.260354859)

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

    def test_incremental_final_importance_caps_apply_by_type(self) -> None:
        capped = apply_incremental_final_importance_caps(
            [
                {"type": "open_question", "importance": 0.99, "content": "Q"},
                {"type": "decision", "importance": 1.0, "content": "D"},
                {"type": "todo", "importance": 0.82, "content": "T"},
            ]
        )

        self.assertEqual(capped[0]["importance"], 0.80)
        self.assertEqual(capped[1]["importance"], 0.92)
        self.assertEqual(capped[2]["importance"], 0.65)

    def test_direct_issue_importance_cap_helpers(self) -> None:
        self.assertEqual(
            calibrate_issue_importance(
                0.95,
                episode_count=6,
                status="open",
                title="meeting agenda",
                summary="weekly meeting agenda and logistics",
            ),
            0.6,
        )
        self.assertEqual(
            calibrate_issue_importance(
                0.95,
                episode_count=6,
                status="open",
                title="tiramisu tasting",
                summary="weekend barbecue and dessert event",
            ),
            0.5,
        )
        self.assertEqual(
            calibrate_issue_importance(
                0.95,
                episode_count=4,
                status="open",
                title="recording instructions",
                summary="turn off microphones and use more comfortable headsets",
            ),
            0.55,
        )

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

    def test_forward_scan_read_is_forced_to_expected_progress_window(self) -> None:
        transcript = "\n".join(f"[S]: line {index}" for index in range(1, 81))
        seed_transcript_lines(self.db_path, self.transcript_id, transcript)

        payload, new_progress = _execute_tool_call(
            db_path=self.db_path,
            transcript_id=self.transcript_id,
            function_call=types.FunctionCall(
                name="read_transcript",
                args={"start_line": 1, "end_line": 5, "purpose": "forward_scan"},
            ),
            max_line=80,
            max_forward_line=40,
            chunk_size=10,
            recent_reads=[],
        )

        self.assertEqual(payload["output"]["start_line"], 41)
        self.assertEqual(payload["output"]["end_line"], 50)
        self.assertEqual(payload["correction"]["requested_start_line"], 1)
        self.assertEqual(payload["correction"]["enforced_start_line"], 41)
        self.assertEqual(new_progress, 50)

    def test_create_l1_object_requires_issue_update_for_current_forward_span(self) -> None:
        transcript = "\n".join(f"[S]: line {index}" for index in range(1, 41))
        seed_transcript_lines(self.db_path, self.transcript_id, transcript)

        payload, new_progress = _execute_tool_call(
            db_path=self.db_path,
            transcript_id=self.transcript_id,
            function_call=types.FunctionCall(
                name="create_l1_object",
                args={
                    "type": "result",
                    "content": "保留一條結果",
                    "importance": 0.6,
                    "evidence": "line 12",
                    "related_topics": [],
                },
            ),
            max_line=40,
            max_forward_line=20,
            chunk_size=20,
            recent_reads=[],
            tool_state=ToolLoopState(
                active_forward_span=ReadSpanRecord(
                    purpose="forward_scan",
                    start_line=1,
                    end_line=20,
                )
            ),
        )

        self.assertIn("update_issue first", payload["error"])
        self.assertEqual(new_progress, 20)

    def test_create_l1_object_auto_links_single_issue_from_current_span(self) -> None:
        transcript = "\n".join(f"[S]: line {index}" for index in range(1, 41))
        seed_transcript_lines(self.db_path, self.transcript_id, transcript)
        upsert_issue(
            self.db_path,
            self.transcript_id,
            title="Demo issue",
            issue_id="ISS-Unit001-demo",
            issue_key="demo_issue",
            status="open",
            importance=0.6,
            summary="Current span issue.",
        )

        payload, _ = _execute_tool_call(
            db_path=self.db_path,
            transcript_id=self.transcript_id,
            function_call=types.FunctionCall(
                name="create_l1_object",
                args={
                    "type": "result",
                    "content": "保留一條結果",
                    "importance": 0.6,
                    "evidence": "line 12",
                    "related_topics": [],
                },
            ),
            max_line=40,
            max_forward_line=20,
            chunk_size=20,
            recent_reads=[],
            tool_state=ToolLoopState(
                active_forward_span=ReadSpanRecord(
                    purpose="forward_scan",
                    start_line=1,
                    end_line=20,
                ),
                forward_span_issue_ids=["ISS-Unit001-demo"],
            ),
        )

        self.assertEqual(payload["output"]["issue_id"], "ISS-Unit001-demo")

    def test_create_l1_object_auto_links_best_matching_issue_from_current_span(self) -> None:
        transcript = "\n".join(f"[S]: line {index}" for index in range(1, 41))
        seed_transcript_lines(self.db_path, self.transcript_id, transcript)
        upsert_issue(
            self.db_path,
            self.transcript_id,
            title="迴聲消除作為下一步",
            issue_id="ISS-Unit001-echo",
            issue_key="echo_next_step",
            status="open",
            importance=0.7,
            summary="ASR 需要迴聲消除來改善表現。",
        )
        upsert_issue(
            self.db_path,
            self.transcript_id,
            title="主轉錄通道版本",
            issue_id="ISS-Unit001-master",
            issue_key="master_channelized_version",
            status="open",
            importance=0.7,
            summary="未來修改都在通道化版本中進行。",
        )

        payload, _ = _execute_tool_call(
            db_path=self.db_path,
            transcript_id=self.transcript_id,
            function_call=types.FunctionCall(
                name="create_l1_object",
                args={
                    "type": "result",
                    "content": "迴聲消除是改善 ASR 的下一個關鍵步驟。",
                    "importance": 0.8,
                    "evidence": "echo cancellation is the critical next step for ASR",
                    "related_topics": ["ASR", "echo cancellation"],
                },
            ),
            max_line=40,
            max_forward_line=20,
            chunk_size=20,
            recent_reads=[],
            tool_state=ToolLoopState(
                active_forward_span=ReadSpanRecord(
                    purpose="forward_scan",
                    start_line=1,
                    end_line=20,
                ),
                forward_span_issue_ids=["ISS-Unit001-echo", "ISS-Unit001-master"],
            ),
        )

        self.assertEqual(payload["output"]["issue_id"], "ISS-Unit001-echo")

    def test_finalization_prompt_mentions_explicit_issue_ids(self) -> None:
        prompt = _build_finalization_prompt(
            transcript_id="Unit001",
            max_line=220,
            tool_state=ToolLoopState(
                active_forward_span=ReadSpanRecord(
                    purpose="forward_scan",
                    start_line=181,
                    end_line=220,
                ),
                final_span=ReadSpanRecord(
                    purpose="forward_scan",
                    start_line=181,
                    end_line=220,
                ),
                forward_span_issue_ids=["ISS-Unit001-a", "ISS-Unit001-b"],
                pending_finalization=True,
            ),
            had_tool_errors=True,
        )

        self.assertIn("Do not call read_transcript again", prompt)
        self.assertIn("ISS-Unit001-a, ISS-Unit001-b", prompt)
        self.assertIn("missing a usable issue_id/issue_key", prompt)

    def test_post_tool_round_action_enters_and_completes_finalization(self) -> None:
        state = ToolLoopState(
            pending_finalization=True,
            final_span=ReadSpanRecord(
                purpose="forward_scan",
                start_line=181,
                end_line=220,
            ),
        )
        self.assertEqual(
            _post_tool_round_action(
                max_forward_line=220,
                max_line=220,
                tool_state=state,
                had_forward_read=True,
                had_tool_errors=False,
            ),
            "finalize_next_round",
        )
        self.assertEqual(
            _post_tool_round_action(
                max_forward_line=220,
                max_line=220,
                tool_state=state,
                had_forward_read=False,
                had_tool_errors=True,
            ),
            "retry_finalization",
        )
        self.assertEqual(
            _post_tool_round_action(
                max_forward_line=220,
                max_line=220,
                tool_state=state,
                had_forward_read=False,
                had_tool_errors=False,
            ),
            "complete",
        )

    def test_auto_tool_rounds_scales_with_transcript_length(self) -> None:
        self.assertEqual(auto_max_tool_rounds(5746, 40), 1192)

        resolved, is_auto = resolve_max_tool_rounds(
            0,
            max_line=5746,
            chunk_size=40,
        )
        self.assertTrue(is_auto)
        self.assertEqual(resolved, 1192)

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
