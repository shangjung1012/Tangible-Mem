from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from share_mem.l1.multi_agent_agents import (  # noqa: E402
    CANDIDATE_SCHEMA,
    IDEA_SCHEMA,
    IDEA_REPAIR_SCHEMA,
    LLMCallTimeoutError,
    MAX_IDEA_UNITS_PER_AGENT,
    MAX_L1_CANDIDATES_PER_TYPE,
    MAX_SEGMENTS_PER_WINDOW,
    SEGMENT_SCHEMA,
    _is_retryable_llm_error,
    idea_unit_agent,
    idea_unit_repair_agent,
    l1_fallback_agent,
    l1_type_agent,
)
from share_mem.l1.multi_agent_pipeline import (  # noqa: E402
    EXTRACTION_BATCH_OVERLAP_UNITS,
    MAX_IDEA_UNITS_PER_EXTRACTION_BATCH,
    TARGET_IDEA_UNITS_PER_EXTRACTION_BATCH,
    build_metrics_summary,
    build_continuation_batches,
    build_previous_batch_context,
    idea_units_for_batch,
    refine_cross_window_boundaries,
    run_multi_agent_l1_pipeline,
)
from share_mem.l1.multi_agent_reducer import (  # noqa: E402
    reduce_l1_patch,
    resolve_cross_type_conflicts,
)
from share_mem.l1.multi_agent_state import (  # noqa: E402
    GroundedCandidate,
    IdeaUnit,
    L1Candidate,
    L1_MULTI_AGENT_TYPE_ORDER,
    SegmentProposal,
    TranscriptLine,
    WindowPlan,
    parse_transcript_lines,
)
from share_mem.l1.multi_agent_validators import (  # noqa: E402
    MAX_IDEA_UNITS_PER_SEGMENT,
    coarsen_segments_for_window,
    normalize_idea_completeness,
    repair_idea_units_for_segment,
    repair_segment_coverage,
)
from share_mem.l1.multi_agent_verifier import ground_candidates, verify_l1_candidates  # noqa: E402


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def call_json(self, stage: str, prompt: str, schema: dict) -> dict:
        self.calls.append((stage, prompt))
        return {
            "candidates": [
                {
                    "source_unit_ids": ["U-S-1-01", "U-S-2-01"],
                    "content": "改用 per-student recall 作為評估方式。",
                    "importance": 0.7,
                    "confidence": 0.9,
                    "rationale": "bounded unit supports a method change",
                    "related_topics": ["evaluation"],
                }
            ]
        }


class NoisyTypeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def call_json(self, stage: str, prompt: str, schema: dict) -> dict:
        self.calls.append((stage, prompt, schema))
        return {
            "candidates": [
                {
                    "source_unit_ids": ["U-1"],
                    "content": "Low ranked local detail.",
                    "importance": 0.4,
                    "confidence": 0.5,
                    "rationale": "weak",
                    "related_topics": [],
                },
                {
                    "source_unit_ids": ["U-1"],
                    "content": "Adopt durable tool calling design.",
                    "importance": 0.95,
                    "confidence": 0.9,
                    "rationale": "durable",
                    "related_topics": ["tool calling"],
                },
                {
                    "source_unit_ids": ["U-1"],
                    "content": "Implement durable memory update flow.",
                    "importance": 0.9,
                    "confidence": 0.88,
                    "rationale": "durable",
                    "related_topics": ["memory"],
                },
                {
                    "source_unit_ids": ["U-1"],
                    "content": "Preserve dynamic transcript segmentation as a durable extraction scope.",
                    "importance": 0.86,
                    "confidence": 0.86,
                    "rationale": "durable",
                    "related_topics": ["segmentation"],
                },
                {
                    "source_unit_ids": ["U-1"],
                    "content": "Use verifier and reducer stages to control candidate quality.",
                    "importance": 0.84,
                    "confidence": 0.84,
                    "rationale": "durable",
                    "related_topics": ["verifier", "reducer"],
                },
                {
                    "source_unit_ids": ["U-1"],
                    "content": "Keep batch as extraction scope rather than final semantic truth.",
                    "importance": 0.82,
                    "confidence": 0.82,
                    "rationale": "durable",
                    "related_topics": ["batch"],
                },
                {
                    "source_unit_ids": ["U-1"],
                    "content": "Allow source candidates to cite multiple idea units.",
                    "importance": 0.8,
                    "confidence": 0.8,
                    "rationale": "durable",
                    "related_topics": ["idea units"],
                },
                {
                    "source_unit_ids": ["U-1"],
                    "content": "Extra local aside that should be trimmed by the safety cap.",
                    "importance": 0.78,
                    "confidence": 0.78,
                    "rationale": "lower ranked",
                    "related_topics": [],
                },
            ]
        }


class FakeFallbackRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def call_json(self, stage: str, prompt: str, schema: dict) -> dict:
        self.calls.append((stage, prompt))
        return {
            "candidates": [
                {
                    "type": "decision",
                    "source_unit_ids": ["U-1"],
                    "content": "保留 tool calling 作為逐段讀取策略。",
                    "importance": 0.62,
                    "confidence": 0.74,
                    "rationale": "fallback saw a durable decision in bounded units",
                    "related_topics": ["tool calling"],
                }
            ]
        }


class FakeIdeaRepairRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def call_json(self, stage: str, prompt: str, schema: dict) -> dict:
        self.calls.append((stage, prompt, schema))
        return {
            "idea_units": [
                {
                    "line_start": 2,
                    "line_end": 3,
                    "text": "The team explores whether dynamic transcript units should replace fixed-size chunking.",
                    "completeness": "High",
                    "uncertainty_note": "",
                }
            ],
            "non_memory_context_ranges": [
                {
                    "line_start": 4,
                    "line_end": 4,
                    "reason": "acknowledgement only",
                }
            ],
        }


class FakeIdeaRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def call_json(self, stage: str, prompt: str, schema: dict) -> dict:
        self.calls.append((stage, prompt, schema))
        return {
            "idea_units": [
                {
                    "line_start": 1,
                    "line_end": 2,
                    "text": "The team discusses dynamic transcript segmentation.",
                    "completeness": "complete",
                    "uncertainty_note": "",
                }
            ]
        }


class FakePipelineRunner:
    def __init__(self, **kwargs) -> None:
        del kwargs
        self.call_records: list[dict] = []


class MultiAgentPipelineTests(unittest.TestCase):
    def test_transport_disconnects_are_retryable(self) -> None:
        try:
            import httpx
        except ImportError:  # pragma: no cover - httpx is installed with google-genai.
            self.skipTest("httpx is not installed")

        self.assertTrue(_is_retryable_llm_error(LLMCallTimeoutError("timed out")))
        self.assertTrue(
            _is_retryable_llm_error(
                httpx.RemoteProtocolError(
                    "Server disconnected without sending a response."
                )
            )
        )

    def test_adaptive_schema_limits_remain_bounded(self) -> None:
        self.assertEqual(
            SEGMENT_SCHEMA["properties"]["segments"]["maxItems"],
            MAX_SEGMENTS_PER_WINDOW,
        )
        self.assertEqual(
            IDEA_SCHEMA["properties"]["idea_units"]["maxItems"],
            MAX_IDEA_UNITS_PER_AGENT,
        )
        self.assertLessEqual(
            IDEA_SCHEMA["properties"]["idea_units"]["maxItems"],
            MAX_IDEA_UNITS_PER_SEGMENT,
        )
        self.assertEqual(
            IDEA_SCHEMA["properties"]["idea_units"]["items"]["properties"][
                "completeness"
            ]["enum"],
            ["complete", "partial", "incomplete", "uncertain"],
        )
        self.assertEqual(
            IDEA_REPAIR_SCHEMA["properties"]["idea_units"]["items"]["properties"][
                "completeness"
            ]["enum"],
            ["complete", "partial", "incomplete", "uncertain"],
        )
        self.assertEqual(
            CANDIDATE_SCHEMA["properties"]["candidates"]["maxItems"],
            MAX_L1_CANDIDATES_PER_TYPE,
        )

    def test_normalize_idea_completeness_maps_model_variants(self) -> None:
        self.assertEqual(normalize_idea_completeness("Complete"), "complete")
        self.assertEqual(normalize_idea_completeness("full"), "complete")
        self.assertEqual(normalize_idea_completeness("High"), "complete")
        self.assertEqual(normalize_idea_completeness("Medium"), "partial")
        self.assertEqual(normalize_idea_completeness("fallback"), "uncertain")
        self.assertEqual(
            normalize_idea_completeness("fallback", allow_internal=True),
            "fallback",
        )

    def test_idea_unit_repair_agent_returns_semantic_units_and_non_memory_ranges(self) -> None:
        runner = FakeIdeaRepairRunner()
        segment = SegmentProposal(
            segment_id="S-0001-01",
            line_start=1,
            line_end=4,
            topic_label="dynamic unit sizing",
            needs_more_context=False,
        )
        lines = parse_transcript_lines(
            "A: fixed chunking might be wrong.\n"
            "B: should dynamic transcript units replace fixed-size chunking?\n"
            "A: topic diversity could decide the boundary.\n"
            "B: okay."
        )

        units, non_memory_ranges = idea_unit_repair_agent(
            runner,
            segment=segment,
            transcript_lines=lines,
            current_units=[],
            validation_report={
                "issues": [
                    {
                        "issue": "uncovered_line_ranges",
                        "uncovered_ranges": [{"start_line": 2, "end_line": 4}],
                    }
                ]
            },
        )

        self.assertEqual(runner.calls[0][0], "idea_unit_repair_agent_S-0001-01")
        self.assertIs(runner.calls[0][2], IDEA_REPAIR_SCHEMA)
        self.assertIn("Completeness rubric:", runner.calls[0][1])
        self.assertIn("partial: the unit is useful", runner.calls[0][1])
        self.assertIn("incomplete: the discussion is cut off", runner.calls[0][1])
        self.assertIn("uncertain: the text is ambiguous", runner.calls[0][1])
        self.assertEqual(units[0].completeness, "complete")
        self.assertEqual(units[0].line_start, 2)
        self.assertEqual(non_memory_ranges[0]["start_line"], 4)

    def test_idea_unit_agent_prompt_defines_completeness_rubric(self) -> None:
        runner = FakeIdeaRunner()
        segment = SegmentProposal(
            segment_id="S-0001-01",
            line_start=1,
            line_end=2,
            topic_label="dynamic segmentation",
            needs_more_context=False,
        )
        lines = parse_transcript_lines(
            "A: Fixed chunking may split a complete idea.\n"
            "B: Dynamic segmentation could preserve the full unit."
        )

        units = idea_unit_agent(
            runner,
            segment=segment,
            transcript_lines=lines,
        )

        prompt = runner.calls[0][1]
        self.assertIs(runner.calls[0][2], IDEA_SCHEMA)
        self.assertIn("Completeness rubric:", prompt)
        self.assertIn("complete: the unit is self-contained", prompt)
        self.assertIn("partial: the unit is useful", prompt)
        self.assertIn("incomplete: the discussion is cut off", prompt)
        self.assertIn("uncertain: the text is ambiguous", prompt)
        self.assertEqual(units[0].completeness, "complete")

    def test_grounding_uses_shared_idea_unit_spans(self) -> None:
        lines = parse_transcript_lines(
            "A: We switched evaluation to per-student recall.\n"
            "B: The old aggregate score hid failures."
        )
        units = [
            IdeaUnit(
                unit_id="U-1",
                segment_id="S-1",
                line_start=1,
                line_end=2,
                text="改用 per-student recall 評估，因為 aggregate score 掩蓋失敗。",
                completeness="complete",
            )
        ]
        candidates = [
            L1Candidate(
                candidate_id="C-method_change-001",
                type="method_change",
                source_unit_ids=["U-1"],
                content="改用 per-student recall 作為評估方式。",
                importance=0.7,
                confidence=0.8,
                rationale="The unit describes a procedure change.",
                related_topics=["evaluation"],
            )
        ]

        grounded = ground_candidates(candidates, idea_units=units, transcript_lines=lines)

        self.assertEqual(grounded[0].evidence_lines, [1, 2])
        self.assertIn("per-student recall", grounded[0].evidence_quote)
        self.assertGreater(grounded[0].support_score, 0.0)

    def test_grounding_preserves_idea_unit_quality_metadata(self) -> None:
        lines = parse_transcript_lines(
            "A: We may need more context before locking the retrieval design.\n"
            "B: The current evidence is incomplete."
        )
        units = [
            IdeaUnit(
                unit_id="U-1",
                segment_id="S-1",
                line_start=1,
                line_end=2,
                text="retrieval design may need more context before being locked",
                completeness="partial",
                uncertainty_note="segment boundary may omit earlier rationale",
            )
        ]
        candidates = [
            L1Candidate(
                candidate_id="C-result-001",
                type="result",
                source_unit_ids=["U-1"],
                content="retrieval design may need more context before being locked",
                importance=0.7,
                confidence=0.8,
                rationale="The unit explicitly marks uncertainty.",
                related_topics=["retrieval"],
            )
        ]

        grounded = ground_candidates(candidates, idea_units=units, transcript_lines=lines)
        result = verify_l1_candidates([grounded[0].__dict__], max_line=2)

        self.assertEqual(grounded[0].source_unit_completeness, ["partial"])
        self.assertEqual(
            grounded[0].source_unit_uncertainty_notes,
            ["segment boundary may omit earlier rationale"],
        )
        self.assertEqual(len(result.verified_candidates), 1)
        self.assertIn(
            "uncertain_source_unit",
            result.verified_candidates[0]["unit_quality_warnings"],
        )
        self.assertIn(
            "source_unit_uncertainty_note",
            result.verified_candidates[0]["unit_quality_warnings"],
        )

    def test_metrics_summary_reports_run_level_quality_signals(self) -> None:
        plan = WindowPlan(
            start_line=1,
            end_line=3,
            lookback_lines=0,
            lookahead_lines=0,
            reason="test",
        )
        segment = SegmentProposal(
            segment_id="S-0001-01",
            line_start=1,
            line_end=3,
            topic_label="test topic",
            needs_more_context=True,
        )
        unit = IdeaUnit(
            unit_id="U-1",
            segment_id="S-0001-01",
            line_start=1,
            line_end=3,
            text="uncertain but useful unit",
            completeness="fallback",
            uncertainty_note="validator fallback",
        )
        raw_candidate = L1Candidate(
            candidate_id="C-result-001",
            type="result",
            source_unit_ids=["U-1"],
            content="uncertain but useful unit",
            importance=0.6,
            confidence=0.7,
            rationale="",
        )

        metrics = build_metrics_summary(
            line_count=3,
            window_plans=[plan],
            initial_segments=[segment],
            final_segments=[segment],
            coverage_reports=[
                {
                    "coverage_rate": 1.0,
                    "repair_segment_ids": ["S-0001-R01"],
                }
            ],
            coarsening_reports=[{"merged_groups": [{"output_segment_id": "S-0001-C01"}]}],
            boundary_refinement_reports=[{"action": "refine"}],
            idea_units=[unit],
            idea_unit_quality_reports=[
                {
                    "coverage_rate": 1.0,
                    "issues": [{"issue": "too_fat_line_span"}],
                    "repairs": [{"action": "replace_with_line_chunks"}],
                    "non_memory_context_ranges": [
                        {"start_line": 2, "end_line": 2}
                    ],
                    "semantic_repair": {
                        "attempted": True,
                        "used_semantic_output": True,
                    },
                }
            ],
            extraction_batches=[{"batch_id": "B-001", "segment_ids": ["S-0001-01"]}],
            continuation_decisions=[{"action": "merge"}],
            previous_context_by_batch={
                "B-002": {
                    "enabled": True,
                    "items": [
                        {
                            "type": "decision",
                            "source_batch_id": "B-001",
                            "content": "Previous decision.",
                        }
                    ],
                }
            },
            raw_candidates=[raw_candidate],
            batch_fallback_reports=[{"batch_id": "B-001"}],
            grounded_candidates=[{"support_score": 0.64}],
            conflict_decisions=[{"action": "keep"}],
            verified_candidates=[
                {
                    "type": "result",
                    "unit_quality_warnings": ["validator_repaired_source_unit"],
                }
            ],
            rejected_candidates=[
                {"verification_reasons": ["weak_grounding", "duplicate_of:C-1"]}
            ],
            memory_objects=[
                {
                    "type": "result",
                    "importance": 0.58,
                }
            ],
            viewpoint_recurrence=[{"viewpoint_key": "x"}],
            llm_call_records=[
                {
                    "stage": "segmentation_1_3",
                    "success": True,
                    "latency_sec": 1.2,
                    "prompt_chars": 400,
                    "response_chars": 80,
                },
                {
                    "stage": "l1_argument_agent_B-001",
                    "success": True,
                    "latency_sec": 2.0,
                    "prompt_chars": 600,
                    "response_chars": 120,
                },
            ],
        )

        self.assertEqual(metrics["segments"]["boundary_refinement_actions"]["refine"], 1)
        self.assertEqual(metrics["idea_units"]["completeness_counts"]["fallback"], 1)
        self.assertEqual(metrics["idea_units"]["semantic_repair_count"], 1)
        self.assertEqual(metrics["idea_units"]["semantic_repair_success_count"], 1)
        self.assertEqual(metrics["idea_units"]["non_memory_context_ranges"], 1)
        self.assertEqual(metrics["idea_units"]["non_memory_context_lines"], 1)
        self.assertEqual(metrics["idea_units"]["deterministic_fallback_count"], 1)
        self.assertEqual(metrics["idea_units"]["compaction_fallback_count"], 0)
        self.assertEqual(metrics["extraction_batches"]["continuation_actions"]["merge"], 1)
        self.assertEqual(metrics["extraction_batches"]["idea_units_per_batch"]["max"], 1.0)
        self.assertEqual(metrics["extraction_packets"]["idea_units_per_packet"]["max"], 1.0)
        self.assertEqual(metrics["extraction_batches"]["oversized_batch_count"], 0)
        self.assertEqual(metrics["extraction_packets"]["oversized_packet_count"], 0)
        self.assertEqual(
            metrics["extraction_batches"]["target_idea_units_per_batch"],
            TARGET_IDEA_UNITS_PER_EXTRACTION_BATCH,
        )
        self.assertEqual(
            metrics["extraction_packets"]["target_idea_units_per_packet"],
            TARGET_IDEA_UNITS_PER_EXTRACTION_BATCH,
        )
        self.assertEqual(
            metrics["extraction_batches"]["max_idea_units_per_batch"],
            MAX_IDEA_UNITS_PER_EXTRACTION_BATCH,
        )
        self.assertEqual(
            metrics["extraction_batches"]["overlap_units_per_split"],
            EXTRACTION_BATCH_OVERLAP_UNITS,
        )
        self.assertEqual(metrics["extraction_batches"]["split_family_count"], 0)
        self.assertEqual(metrics["extraction_batches"]["tiny_remainder_avoided_count"], 0)
        self.assertTrue(metrics["previous_context"]["enabled"])
        self.assertEqual(metrics["previous_context"]["extraction_packet_count"], 1)
        self.assertEqual(metrics["previous_context"]["batches_with_items"], 1)
        self.assertEqual(metrics["previous_context"]["packets_with_items"], 1)
        self.assertEqual(metrics["previous_context"]["items_per_batch"]["max"], 1.0)
        self.assertEqual(metrics["previous_context"]["items_per_packet"]["max"], 1.0)
        self.assertEqual(metrics["candidates"]["raw_by_type"]["result"], 1)
        self.assertEqual(metrics["candidates"]["rejection_reasons"]["duplicate_of"], 1)
        self.assertEqual(metrics["final_l1"]["viewpoint_recurrence_count"], 1)
        self.assertEqual(metrics["llm"]["call_count"], 2)
        self.assertEqual(metrics["llm"]["calls_by_stage"]["segmentation_agent"], 1)
        self.assertEqual(metrics["llm"]["calls_by_stage"]["l1_argument_agent"], 1)

    def test_pipeline_writes_failure_status_and_partial_summary(self) -> None:
        def broken_segmentation(*args, **kwargs):
            del args, kwargs
            raise RuntimeError("segmentation exploded")

        with tempfile.TemporaryDirectory() as tmp:
            with patch("share_mem.l1.multi_agent_pipeline.MultiAgentLLMRunner", FakePipelineRunner):
                with patch("share_mem.l1.multi_agent_pipeline.segmentation_agent", broken_segmentation):
                    with self.assertRaises(RuntimeError):
                        run_multi_agent_l1_pipeline(
                            model_name="gemini-test",
                            api_key=[],
                            transcript="A: important discussion",
                            meeting_id="UnitRun",
                            source_file="unit.txt",
                            timestamp="2026-05-05T00:00:00Z",
                            meeting_date="2026-05-05",
                            existing_topics=[],
                            research_log_dir=Path(tmp),
                            window_size=20,
                        )

            run_dirs = [path for path in Path(tmp).iterdir() if path.is_dir()]
            self.assertEqual(len(run_dirs), 1)
            status = json.loads((run_dirs[0] / "status.json").read_text())
            summary = json.loads((run_dirs[0] / "run_summary.json").read_text())

        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["error"]["type"], "RuntimeError")
        self.assertIn("segmentation_agent", status["last_started_stage"])
        self.assertEqual(status["last_completed_stage"], "context_planner:done")
        self.assertEqual(summary["metrics"]["windows"]["count"], 1)
        self.assertEqual(summary["metrics"]["segments"]["final_count"], 0)

    def test_grounding_rejects_mismatch_even_with_high_candidate_confidence(self) -> None:
        lines = parse_transcript_lines("A: Lunch will be delivered at noon.")
        units = [
            IdeaUnit(
                unit_id="U-1",
                segment_id="S-1",
                line_start=1,
                line_end=1,
                text="午餐會在中午送達。",
                completeness="complete",
            )
        ]
        candidates = [
            L1Candidate(
                candidate_id="C-result-001",
                type="result",
                source_unit_ids=["U-1"],
                content="模型準確率大幅改善。",
                importance=0.8,
                confidence=1.0,
                rationale="upstream model is overconfident",
                related_topics=["model"],
            )
        ]

        grounded = ground_candidates(candidates, idea_units=units, transcript_lines=lines)
        result = verify_l1_candidates([grounded[0].__dict__], max_line=1)

        self.assertEqual(grounded[0].support_score, 0.0)
        self.assertEqual(len(result.verified_candidates), 0)
        self.assertIn("weak_grounding", result.rejected_candidates[0]["verification_reasons"])

    def test_verifier_keeps_near_threshold_complete_grounding_as_warning(self) -> None:
        candidate = {
            "candidate_id": "C-open-question-001",
            "type": "open_question",
            "source_unit_ids": ["U-1"],
            "content": "The team still needs to compare bilingual retrieval quality.",
            "importance": 0.72,
            "confidence": 0.9,
            "rationale": "The complete source unit names the unresolved comparison.",
            "related_topics": ["retrieval", "evaluation"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_lines": [4, 5],
            "evidence_quote": "We need to compare whether bilingual retrieval is good enough.",
            "support_score": 0.17,
            "source_unit_completeness": ["complete"],
            "source_unit_uncertainty_notes": [],
        }

        result = verify_l1_candidates([candidate], max_line=10)

        self.assertEqual(len(result.verified_candidates), 1)
        self.assertEqual(len(result.rejected_candidates), 0)
        self.assertIn(
            "near_threshold_grounding",
            result.verified_candidates[0]["unit_quality_warnings"],
        )
        self.assertNotIn(
            "weak_grounding",
            result.verified_candidates[0]["verification_reasons"],
        )

    def test_verifier_rejects_near_threshold_uncertain_source_unit(self) -> None:
        candidate = {
            "candidate_id": "C-open-question-001",
            "type": "open_question",
            "source_unit_ids": ["U-1"],
            "content": "The team still needs to compare bilingual retrieval quality.",
            "importance": 0.72,
            "confidence": 0.9,
            "rationale": "",
            "related_topics": ["retrieval", "evaluation"],
            "evidence_lines": [4, 5],
            "evidence_quote": "We need to compare whether bilingual retrieval is good enough.",
            "support_score": 0.17,
            "source_unit_completeness": ["partial"],
            "source_unit_uncertainty_notes": [],
        }

        result = verify_l1_candidates([candidate], max_line=10)

        self.assertEqual(len(result.verified_candidates), 0)
        self.assertIn("weak_grounding", result.rejected_candidates[0]["verification_reasons"])

    def test_verifier_rejects_below_near_threshold_grounding(self) -> None:
        candidate = {
            "candidate_id": "C-open-question-001",
            "type": "open_question",
            "source_unit_ids": ["U-1"],
            "content": "The team still needs to compare bilingual retrieval quality.",
            "importance": 0.72,
            "confidence": 1.0,
            "rationale": "",
            "related_topics": ["retrieval", "evaluation"],
            "evidence_lines": [4, 5],
            "evidence_quote": "We need to compare whether bilingual retrieval is good enough.",
            "support_score": 0.12,
            "source_unit_completeness": ["complete"],
            "source_unit_uncertainty_notes": [],
        }

        result = verify_l1_candidates([candidate], max_line=10)

        self.assertEqual(len(result.verified_candidates), 0)
        self.assertIn("weak_grounding", result.rejected_candidates[0]["verification_reasons"])

    def test_type_agent_is_bounded_to_supplied_segment_units(self) -> None:
        runner = FakeRunner()
        scoped_units = [
            IdeaUnit(
                unit_id="U-S-1-01",
                segment_id="S-1",
                line_start=1,
                line_end=1,
                text="改用 per-student recall 評估。",
                completeness="complete",
            )
        ]

        candidates = l1_type_agent(
            runner,
            obj_type="method_change",
            idea_units=scoped_units,
            existing_topics=[],
            extraction_scope="B-001",
            segment_ids=["S-1"],
        )

        self.assertEqual(candidates[0].extraction_scope, "B-001")
        self.assertEqual(candidates[0].segment_ids, ["S-1"])
        self.assertEqual(candidates[0].source_unit_ids, ["U-S-1-01"])
        self.assertIn("U-S-1-01", runner.calls[0][1])
        self.assertNotIn("U-S-2-01", runner.calls[0][1])

    def test_type_agent_supports_all_formal_l1_types(self) -> None:
        units = [
            IdeaUnit(
                unit_id="U-S-1-01",
                segment_id="S-1",
                line_start=1,
                line_end=2,
                text="這段保留決策理由，也留下尚未解決的研究問題。",
                completeness="complete",
            )
        ]

        for obj_type in L1_MULTI_AGENT_TYPE_ORDER:
            runner = FakeRunner()
            candidates = l1_type_agent(
                runner,
                obj_type=obj_type,
                idea_units=units,
                existing_topics=[],
                extraction_scope="B-001",
                segment_ids=["S-1"],
            )
            self.assertEqual(candidates[0].type, obj_type)
            self.assertIn(f"l1_{obj_type}_agent", runner.calls[0][0])

    def test_cross_window_continuation_merge_builds_one_bounded_batch(self) -> None:
        segments = [
            SegmentProposal(
                segment_id="S-0001-01",
                line_start=1,
                line_end=2,
                topic_label="evaluation method",
                needs_more_context=True,
            ),
            SegmentProposal(
                segment_id="S-0003-01",
                line_start=3,
                line_end=4,
                topic_label="evaluation method",
                needs_more_context=False,
            ),
        ]
        units = [
            IdeaUnit(
                unit_id="U-1",
                segment_id="S-0001-01",
                line_start=1,
                line_end=2,
                text="評估方法討論開始。",
                completeness="partial",
            ),
            IdeaUnit(
                unit_id="U-2",
                segment_id="S-0003-01",
                line_start=3,
                line_end=4,
                text="評估方法決議完成。",
                completeness="complete",
            ),
        ]

        batches, decisions = build_continuation_batches(segments)
        batch_units = idea_units_for_batch(units, batches[0])

        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["segment_ids"], ["S-0001-01", "S-0003-01"])
        self.assertEqual([unit.unit_id for unit in batch_units], ["U-1", "U-2"])
        self.assertEqual(decisions[0]["action"], "merge")

    def test_cross_window_topic_continuity_merges_without_flag(self) -> None:
        segments = [
            SegmentProposal(
                segment_id="S-0001-03",
                line_start=75,
                line_end=80,
                topic_label="dynamic chunking method",
                needs_more_context=False,
            ),
            SegmentProposal(
                segment_id="S-0081-01",
                line_start=81,
                line_end=88,
                topic_label="dynamic chunking method",
                needs_more_context=False,
            ),
        ]

        batches, decisions = build_continuation_batches(segments)

        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["segment_ids"], ["S-0001-03", "S-0081-01"])
        self.assertEqual(decisions[0]["action"], "merge")
        self.assertIn("cross_window_topic_continuity", decisions[0]["reason"])

    def test_continuation_merge_splits_oversized_batches_by_idea_unit_cap(self) -> None:
        segments = [
            SegmentProposal(
                segment_id=f"S-0001-{index:02d}",
                line_start=(index - 1) * 10 + 1,
                line_end=index * 10,
                topic_label="dynamic memory update",
                needs_more_context=True,
            )
            for index in range(1, 5)
        ]
        units = [
            IdeaUnit(
                unit_id=f"U-{segment.segment_id}-{unit_index:02d}",
                segment_id=segment.segment_id,
                line_start=segment.line_start,
                line_end=segment.line_end,
                text=f"{segment.segment_id} unit {unit_index}",
                completeness="complete",
            )
            for segment in segments
            for unit_index in range(1, 9)
        ]

        batches, decisions = build_continuation_batches(segments, idea_units=units)
        batch_unit_counts = [len(idea_units_for_batch(units, batch)) for batch in batches]

        self.assertGreater(len(batches), 1)
        self.assertTrue(
            all(count <= MAX_IDEA_UNITS_PER_EXTRACTION_BATCH for count in batch_unit_counts)
        )
        self.assertTrue(all(count > TARGET_IDEA_UNITS_PER_EXTRACTION_BATCH for count in batch_unit_counts))
        self.assertTrue(any("parent_batch_id" in batch for batch in batches))
        self.assertTrue(any(decision["action"] == "split_large_batch" for decision in decisions))

    def test_single_segment_over_target_but_within_max_is_not_split(self) -> None:
        segment = SegmentProposal(
            segment_id="S-0001-01",
            line_start=1,
            line_end=11,
            topic_label="tool calling extraction design",
            needs_more_context=False,
        )
        units = [
            IdeaUnit(
                unit_id=f"U-{index:02d}",
                segment_id=segment.segment_id,
                line_start=index,
                line_end=index,
                text=f"durable idea unit {index}",
                completeness="complete",
            )
            for index in range(1, TARGET_IDEA_UNITS_PER_EXTRACTION_BATCH + 2)
        ]

        batches, decisions = build_continuation_batches([segment], idea_units=units)
        batch_units = idea_units_for_batch(units, batches[0])

        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batch_units), TARGET_IDEA_UNITS_PER_EXTRACTION_BATCH + 1)
        self.assertNotIn("parent_batch_id", batches[0])
        self.assertTrue(batches[0]["tiny_remainder_avoided"])
        self.assertFalse(any(decision["action"] == "split_large_batch" for decision in decisions))

    def test_continuation_group_over_target_but_within_max_is_not_split(self) -> None:
        segments = [
            SegmentProposal(
                segment_id="S-0001-01",
                line_start=1,
                line_end=7,
                topic_label="dynamic memory update",
                needs_more_context=True,
            ),
            SegmentProposal(
                segment_id="S-0008-01",
                line_start=8,
                line_end=13,
                topic_label="dynamic memory update",
                needs_more_context=False,
            ),
        ]
        units = [
            IdeaUnit(
                unit_id=f"U-{index:02d}",
                segment_id=segments[0].segment_id if index <= 7 else segments[1].segment_id,
                line_start=index,
                line_end=index,
                text=f"durable idea unit {index}",
                completeness="complete",
            )
            for index in range(1, TARGET_IDEA_UNITS_PER_EXTRACTION_BATCH + 4)
        ]

        batches, decisions = build_continuation_batches(segments, idea_units=units)
        batch_units = idea_units_for_batch(units, batches[0])

        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["segment_ids"], ["S-0001-01", "S-0008-01"])
        self.assertEqual(len(batch_units), TARGET_IDEA_UNITS_PER_EXTRACTION_BATCH + 3)
        self.assertNotIn("parent_batch_id", batches[0])
        self.assertTrue(any(decision["action"] == "merge" for decision in decisions))

    def test_single_large_segment_splits_into_bounded_unit_chunks(self) -> None:
        segment = SegmentProposal(
            segment_id="S-0001-01",
            line_start=1,
            line_end=40,
            topic_label="tool calling extraction design",
            needs_more_context=False,
        )
        units = [
            IdeaUnit(
                unit_id=f"U-{index:02d}",
                segment_id=segment.segment_id,
                line_start=index,
                line_end=index,
                text=f"durable idea unit {index}",
                completeness="complete",
            )
            for index in range(1, 21)
        ]

        batches, decisions = build_continuation_batches([segment], idea_units=units)
        batch_unit_counts = [len(idea_units_for_batch(units, batch)) for batch in batches]

        self.assertEqual(len(batches), 2)
        self.assertEqual(
            batch_unit_counts,
            [11, 11],
        )
        self.assertTrue(all("unit_ids" in batch for batch in batches))
        self.assertEqual(batches[0]["parent_batch_id"], batches[1]["parent_batch_id"])
        self.assertEqual(batches[0]["split_index"], 1)
        self.assertEqual(batches[1]["split_index"], 2)
        self.assertEqual(batches[0]["split_count"], 2)
        self.assertEqual(batches[0]["overlap_unit_ids"], ["U-10", "U-11"])
        self.assertEqual(batches[1]["overlap_unit_ids"], ["U-10", "U-11"])
        self.assertIn("single segment exceeded", batches[0]["split_reason"])
        self.assertEqual(batches[0]["semantic_parent_segment_ids"], ["S-0001-01"])
        self.assertTrue(any(decision["action"] == "split_large_batch" for decision in decisions))

    def test_cross_window_boundary_text_merges_without_matching_topic_labels(self) -> None:
        transcript_lines = parse_transcript_lines(
            "A: Gemini reads five lines and decides whether the answer is complete.\n"
            "B: If the answer is incomplete, Function Calling can extend the read range.\n"
            "A: The next read range and chunk still discuss whether the answer is complete.\n"
            "B: Reading one sentence at a time would create too many Function Calling calls.\n"
        )
        segments = [
            SegmentProposal(
                segment_id="S-0001-01",
                line_start=1,
                line_end=2,
                topic_label="read function parameters",
                needs_more_context=False,
            ),
            SegmentProposal(
                segment_id="S-0003-01",
                line_start=3,
                line_end=4,
                topic_label="compute tradeoff",
                needs_more_context=False,
            ),
        ]

        batches, decisions = build_continuation_batches(
            segments,
            transcript_lines=transcript_lines,
        )

        self.assertEqual(len(batches), 1)
        self.assertEqual(decisions[0]["action"], "merge")
        self.assertIn("boundary_similarity", decisions[0]["reason"])

    def test_cross_window_boundary_refinement_resegments_joined_span(self) -> None:
        transcript_lines = [
            *[
                TranscriptLine(line_id=line_id, text="forgetting decay memory")
                for line_id in range(142, 161)
            ],
            *[
                TranscriptLine(line_id=line_id, text="demo dataset memory")
                for line_id in range(161, 184)
            ],
        ]
        segments = [
            SegmentProposal(
                segment_id="S-0081-C05",
                line_start=142,
                line_end=160,
                topic_label="forgetting and demo strategy",
                needs_more_context=False,
            ),
            SegmentProposal(
                segment_id="S-0161-C01",
                line_start=161,
                line_end=183,
                topic_label="demo strategy and forgetting",
                needs_more_context=False,
            ),
        ]

        def fake_refiner(left, right, plan, reason):
            del left, right, reason
            return [
                SegmentProposal(
                    segment_id="S-0142-01",
                    line_start=142,
                    line_end=156,
                    topic_label="forgetting mechanism",
                    needs_more_context=False,
                ),
                SegmentProposal(
                    segment_id="S-0142-02",
                    line_start=157,
                    line_end=172,
                    topic_label="demo dataset strategy",
                    needs_more_context=False,
                ),
                SegmentProposal(
                    segment_id="S-0142-03",
                    line_start=173,
                    line_end=183,
                    topic_label="presentation narrative",
                    needs_more_context=False,
                ),
            ], {"test_plan": [plan.start_line, plan.end_line]}

        refined, reports = refine_cross_window_boundaries(
            segments,
            transcript_lines=transcript_lines,
            refine_span=fake_refiner,
        )

        self.assertEqual([(s.line_start, s.line_end) for s in refined], [(142, 156), (157, 172), (173, 183)])
        self.assertEqual(reports[0]["action"], "refine")
        self.assertEqual(reports[0]["source_segment_ids"], ["S-0081-C05", "S-0161-C01"])
        self.assertEqual(reports[0]["metadata"]["test_plan"], [142, 183])

    def test_same_window_similar_segments_without_flag_stay_separate(self) -> None:
        segments = [
            SegmentProposal(
                segment_id="S-0001-01",
                line_start=1,
                line_end=8,
                topic_label="dynamic chunking method",
                needs_more_context=False,
            ),
            SegmentProposal(
                segment_id="S-0001-02",
                line_start=9,
                line_end=16,
                topic_label="dynamic chunking method",
                needs_more_context=False,
            ),
        ]

        batches, decisions = build_continuation_batches(segments)

        self.assertEqual(len(batches), 2)
        self.assertEqual(decisions[0]["action"], "keep_separate")
        self.assertIn("no_continuation_flag", decisions[0]["reason"])

    def test_segment_coverage_validator_repairs_uncovered_lines(self) -> None:
        plan = WindowPlan(
            start_line=1,
            end_line=10,
            lookback_lines=0,
            lookahead_lines=0,
            reason="test",
        )
        segments = [
            SegmentProposal(
                segment_id="S-0001-01",
                line_start=1,
                line_end=3,
                topic_label="opening",
                needs_more_context=False,
            ),
            SegmentProposal(
                segment_id="S-0001-02",
                line_start=7,
                line_end=10,
                topic_label="decision",
                needs_more_context=False,
            ),
        ]

        repaired, report = repair_segment_coverage(plan, segments)

        self.assertEqual(report["coverage_rate"], 0.7)
        self.assertEqual(report["uncovered_ranges"], [{"start_line": 4, "end_line": 6}])
        self.assertEqual(report["repair_segment_ids"], ["S-0001-R01"])
        self.assertEqual(len(repaired), 3)
        self.assertEqual(repaired[-1].line_start, 4)
        self.assertEqual(repaired[-1].line_end, 6)
        self.assertTrue(repaired[-1].needs_more_context)
        self.assertIn("opening", repaired[-1].topic_label)
        self.assertIn("decision", repaired[-1].topic_label)

    def test_segment_coarsening_merges_micro_segments(self) -> None:
        plan = WindowPlan(
            start_line=1,
            end_line=24,
            lookback_lines=0,
            lookahead_lines=0,
            reason="test",
        )
        segments = [
            SegmentProposal(
                segment_id=f"S-0001-{index:02d}",
                line_start=(index - 1) * 3 + 1,
                line_end=index * 3,
                topic_label=f"topic {index}",
                needs_more_context=False,
            )
            for index in range(1, 9)
        ]

        coarsened, report = coarsen_segments_for_window(plan, segments)

        self.assertLess(len(coarsened), len(segments))
        self.assertEqual(coarsened[0].line_start, 1)
        self.assertGreaterEqual(coarsened[0].line_end, 8)
        self.assertTrue(report["merged_groups"])

    def test_idea_unit_validator_replaces_fat_unit_with_chunks(self) -> None:
        transcript_lines = parse_transcript_lines(
            "\n".join(f"Speaker: important detail {index}" for index in range(1, 13))
        )
        segment = SegmentProposal(
            segment_id="S-0001-01",
            line_start=1,
            line_end=12,
            topic_label="tool calling flow",
            needs_more_context=False,
        )
        units = [
            IdeaUnit(
                unit_id="U-fat",
                segment_id="S-0001-01",
                line_start=1,
                line_end=12,
                text="This unit mixes too many lines into one oversized idea.",
                completeness="complete",
            )
        ]

        repaired, report = repair_idea_units_for_segment(
            segment=segment,
            units=units,
            transcript_lines=transcript_lines,
        )

        self.assertEqual([unit.line_start for unit in repaired], [1, 9])
        self.assertEqual([unit.line_end for unit in repaired], [8, 12])
        self.assertTrue(any(issue["issue"] == "too_fat_line_span" for issue in report["issues"]))
        self.assertEqual(report["coverage_rate"], 1.0)

    def test_idea_unit_validator_can_diagnose_fat_unit_before_fallback(self) -> None:
        transcript_lines = parse_transcript_lines(
            "\n".join(f"Speaker: important detail {index}" for index in range(1, 13))
        )
        segment = SegmentProposal(
            segment_id="S-0001-01",
            line_start=1,
            line_end=12,
            topic_label="tool calling flow",
            needs_more_context=False,
        )
        units = [
            IdeaUnit(
                unit_id="U-fat",
                segment_id="S-0001-01",
                line_start=1,
                line_end=12,
                text="This unit mixes too many lines into one oversized idea.",
                completeness="complete",
            )
        ]

        repaired, report = repair_idea_units_for_segment(
            segment=segment,
            units=units,
            transcript_lines=transcript_lines,
            deterministic_fallback=False,
        )

        self.assertEqual(repaired, [])
        self.assertTrue(any(issue["issue"] == "too_fat_line_span" for issue in report["issues"]))
        self.assertFalse(
            any(repair["action"] == "replace_with_line_chunks" for repair in report["repairs"])
        )

    def test_idea_unit_validator_compacts_overfragmented_units(self) -> None:
        transcript_lines = parse_transcript_lines(
            "\n".join(f"Speaker: detail {index}" for index in range(1, 17))
        )
        segment = SegmentProposal(
            segment_id="S-0001-01",
            line_start=1,
            line_end=16,
            topic_label="tool calling flow",
            needs_more_context=False,
        )
        units = [
            IdeaUnit(
                unit_id=f"U-{index}",
                segment_id="S-0001-01",
                line_start=index,
                line_end=index,
                text=f"Durable detail {index}",
                completeness="complete",
            )
            for index in range(1, 17)
        ]

        repaired, report = repair_idea_units_for_segment(
            segment=segment,
            units=units,
            transcript_lines=transcript_lines,
        )

        self.assertLessEqual(len(repaired), MAX_IDEA_UNITS_PER_SEGMENT)
        self.assertTrue(any(issue["issue"] == "too_many_units" for issue in report["issues"]))
        self.assertTrue(any(unit.completeness == "compacted" for unit in repaired))

    def test_idea_unit_validator_can_diagnose_overfragmentation_before_compaction(self) -> None:
        transcript_lines = parse_transcript_lines(
            "\n".join(f"Speaker: detail {index}" for index in range(1, 17))
        )
        segment = SegmentProposal(
            segment_id="S-0001-01",
            line_start=1,
            line_end=16,
            topic_label="tool calling flow",
            needs_more_context=False,
        )
        units = [
            IdeaUnit(
                unit_id=f"U-{index}",
                segment_id="S-0001-01",
                line_start=index,
                line_end=index,
                text=f"Durable detail {index}",
                completeness="complete",
            )
            for index in range(1, 17)
        ]

        repaired, report = repair_idea_units_for_segment(
            segment=segment,
            units=units,
            transcript_lines=transcript_lines,
            deterministic_fallback=False,
        )

        self.assertGreater(len(repaired), MAX_IDEA_UNITS_PER_SEGMENT)
        self.assertTrue(any(issue["issue"] == "too_many_units" for issue in report["issues"]))
        self.assertFalse(any(unit.completeness == "compacted" for unit in repaired))

    def test_idea_unit_validator_adds_fallback_for_uncovered_lines(self) -> None:
        transcript_lines = parse_transcript_lines(
            "\n".join(f"Speaker: durable detail {index}" for index in range(1, 7))
        )
        segment = SegmentProposal(
            segment_id="S-0001-01",
            line_start=1,
            line_end=6,
            topic_label="tool calling flow",
            needs_more_context=False,
        )
        units = [
            IdeaUnit(
                unit_id="U-1",
                segment_id="S-0001-01",
                line_start=1,
                line_end=2,
                text="Opening durable detail.",
                completeness="complete",
            ),
            IdeaUnit(
                unit_id="U-2",
                segment_id="S-0001-01",
                line_start=5,
                line_end=6,
                text="Closing durable detail.",
                completeness="complete",
            ),
        ]

        repaired, report = repair_idea_units_for_segment(
            segment=segment,
            units=units,
            transcript_lines=transcript_lines,
        )

        self.assertEqual(report["coverage_rate"], 1.0)
        self.assertTrue(
            any(repair["action"] == "add_fallback_for_uncovered_lines" for repair in report["repairs"])
        )
        self.assertTrue(any(unit.line_start == 3 and unit.line_end == 4 for unit in repaired))

    def test_idea_unit_validator_can_diagnose_uncovered_lines_before_fallback(self) -> None:
        transcript_lines = parse_transcript_lines(
            "\n".join(f"Speaker: durable detail {index}" for index in range(1, 7))
        )
        segment = SegmentProposal(
            segment_id="S-0001-01",
            line_start=1,
            line_end=6,
            topic_label="tool calling flow",
            needs_more_context=False,
        )
        units = [
            IdeaUnit(
                unit_id="U-1",
                segment_id="S-0001-01",
                line_start=1,
                line_end=2,
                text="Opening durable detail.",
                completeness="complete",
            ),
            IdeaUnit(
                unit_id="U-2",
                segment_id="S-0001-01",
                line_start=5,
                line_end=6,
                text="Closing durable detail.",
                completeness="complete",
            ),
        ]

        repaired, report = repair_idea_units_for_segment(
            segment=segment,
            units=units,
            transcript_lines=transcript_lines,
            deterministic_fallback=False,
        )

        self.assertEqual([(unit.line_start, unit.line_end) for unit in repaired], [(1, 2), (5, 6)])
        self.assertTrue(any(issue["issue"] == "uncovered_line_ranges" for issue in report["issues"]))
        self.assertFalse(
            any(repair["action"] == "add_fallback_for_uncovered_lines" for repair in report["repairs"])
        )

    def test_idea_unit_validator_respects_non_memory_ranges_without_fallback(self) -> None:
        transcript_lines = parse_transcript_lines(
            "\n".join(f"Speaker: durable detail {index}" for index in range(1, 7))
        )
        segment = SegmentProposal(
            segment_id="S-0001-01",
            line_start=1,
            line_end=6,
            topic_label="tool calling flow",
            needs_more_context=False,
        )
        units = [
            IdeaUnit(
                unit_id="U-1",
                segment_id="S-0001-01",
                line_start=1,
                line_end=2,
                text="Opening durable detail.",
                completeness="complete",
            ),
            IdeaUnit(
                unit_id="U-2",
                segment_id="S-0001-01",
                line_start=5,
                line_end=6,
                text="Closing durable detail.",
                completeness="complete",
            ),
        ]

        repaired, report = repair_idea_units_for_segment(
            segment=segment,
            units=units,
            transcript_lines=transcript_lines,
            non_memory_ranges=[
                {"start_line": 3, "end_line": 4, "reason": "acknowledgement only"}
            ],
        )

        self.assertEqual(report["coverage_rate"], 1.0)
        self.assertEqual(report["non_memory_context_ranges"], [{"start_line": 3, "end_line": 4}])
        self.assertFalse(
            any(repair["action"] == "add_fallback_for_uncovered_lines" for repair in report["repairs"])
        )
        self.assertEqual([(unit.line_start, unit.line_end) for unit in repaired], [(1, 2), (5, 6)])

    def test_idea_unit_validator_sorts_units_after_repairs(self) -> None:
        transcript_lines = parse_transcript_lines(
            "\n".join(f"Speaker: durable detail {index}" for index in range(1, 6))
        )
        segment = SegmentProposal(
            segment_id="S-0001-01",
            line_start=1,
            line_end=5,
            topic_label="tool calling flow",
            needs_more_context=False,
        )
        units = [
            IdeaUnit(
                unit_id="U-late",
                segment_id="S-0001-01",
                line_start=4,
                line_end=5,
                text="Closing durable detail.",
                completeness="complete",
            ),
            IdeaUnit(
                unit_id="U-early",
                segment_id="S-0001-01",
                line_start=1,
                line_end=1,
                text="Opening durable detail.",
                completeness="complete",
            ),
        ]

        repaired, report = repair_idea_units_for_segment(
            segment=segment,
            units=units,
            transcript_lines=transcript_lines,
        )

        self.assertEqual(report["coverage_rate"], 1.0)
        self.assertEqual(
            [(unit.line_start, unit.line_end) for unit in repaired],
            [(1, 1), (2, 3), (4, 5)],
        )

    def test_type_agent_caps_candidates_per_batch(self) -> None:
        runner = NoisyTypeRunner()
        units = [
            IdeaUnit(
                unit_id="U-1",
                segment_id="S-0001-01",
                line_start=1,
                line_end=2,
                text="Tool calling memory update flow is adopted.",
                completeness="complete",
            )
        ]

        candidates = l1_type_agent(
            runner,
            obj_type="decision",
            idea_units=units,
            existing_topics=[],
            batch_metadata={
                "parent_batch_id": "PB-001",
                "split_index": 1,
                "split_count": 2,
                "split_reason": "single segment exceeded 14 idea units",
                "overlap_unit_ids": ["U-1"],
                "semantic_parent_segment_ids": ["S-0001-01"],
            },
            extraction_scope="B-001",
            segment_ids=["S-0001-01"],
        )

        prompt = runner.calls[0][1]
        self.assertIs(runner.calls[0][2], CANDIDATE_SCHEMA)
        self.assertIn("Normally return 0-4 candidates", prompt)
        self.assertIn(f"up to {MAX_L1_CANDIDATES_PER_TYPE}", prompt)
        self.assertIn("Do not pad", prompt)
        self.assertIn("do not restate each idea unit as a candidate", prompt)
        self.assertIn("Split-family scope metadata (not evidence):", prompt)
        self.assertIn("parent_extraction_packet_id=PB-001", prompt)
        self.assertIn("overlap_unit_ids=U-1", prompt)
        self.assertIn("Do not cite sibling metadata", prompt)
        self.assertEqual(len(candidates), MAX_L1_CANDIDATES_PER_TYPE)
        self.assertEqual(candidates[0].content, "Adopt durable tool calling design.")
        self.assertNotIn("Low ranked local detail.", [candidate.content for candidate in candidates])
        self.assertNotIn(
            "Extra local aside that should be trimmed by the safety cap.",
            [candidate.content for candidate in candidates],
        )

    def test_previous_batch_context_keeps_recent_high_confidence_candidates(self) -> None:
        long_content = "A" * 220
        context = build_previous_batch_context(
            [
                {
                    "batch_id": "B-001",
                    "candidates": [
                        {
                            "type": "decision",
                            "content": long_content,
                            "confidence": 0.9,
                            "extraction_scope": "B-001",
                        },
                        {
                            "type": "todo",
                            "content": "Low-confidence candidate should not leak forward.",
                            "confidence": 0.4,
                            "extraction_scope": "B-001",
                        },
                    ],
                },
                {
                    "batch_id": "B-002",
                    "candidates": [
                        {
                            "type": "open_question",
                            "content": "Whether bilingual retrieval needs a separate evaluation remains open.",
                            "confidence": 0.86,
                            "extraction_scope": "B-002",
                        }
                    ],
                },
            ],
            current_batch_id="B-003",
            enabled=True,
        )

        self.assertTrue(context["enabled"])
        self.assertEqual(context["source_batch_ids"], ["B-001", "B-002"])
        self.assertEqual([item["type"] for item in context["items"]], ["decision", "open_question"])
        self.assertLessEqual(len(context["items"][0]["content"]), 160)

    def test_type_agent_prompt_marks_previous_context_read_only(self) -> None:
        runner = FakeRunner()
        units = [
            IdeaUnit(
                unit_id="U-S-1-01",
                segment_id="S-1",
                line_start=1,
                line_end=1,
                text="決定比較 multi-agent L1 與舊 bridge 的差異。",
                completeness="complete",
            )
        ]

        candidates = l1_type_agent(
            runner,
            obj_type="decision",
            idea_units=units,
            existing_topics=[],
            previous_context={
                "enabled": True,
                "items": [
                    {
                        "type": "open_question",
                        "source_batch_id": "B-001",
                        "content": "是否需要比較 bilingual retrieval 還不確定。",
                    }
                ],
            },
            extraction_scope="B-002",
            segment_ids=["S-1"],
        )

        prompt = runner.calls[0][1]
        self.assertIn(
            "Previous extraction-packet context (unverified, read-only; not evidence)",
            prompt,
        )
        self.assertIn("not passed grounding or final reduction yet", prompt)
        self.assertIn("Do not increase candidate count", prompt)
        self.assertIn("Every source_unit_id must still come from the current bounded idea units", prompt)
        self.assertIn("[B-001 open_question]", prompt)
        self.assertEqual(candidates[0].source_unit_ids, ["U-S-1-01"])

    def test_fallback_l1_agent_returns_bounded_candidate(self) -> None:
        runner = FakeFallbackRunner()
        units = [
            IdeaUnit(
                unit_id="U-1",
                segment_id="S-0001-01",
                line_start=1,
                line_end=2,
                text="決定保留 tool calling 作為逐段讀取策略。",
                completeness="complete",
            )
        ]

        candidates = l1_fallback_agent(
            runner,
            idea_units=units,
            existing_topics=[],
            extraction_scope="B-001",
            segment_ids=["S-0001-01"],
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].type, "decision")
        self.assertEqual(candidates[0].source_unit_ids, ["U-1"])
        self.assertIn("U-1", runner.calls[0][1])

    def test_reducer_dedupes_same_evidence_and_caps_single_line_result(self) -> None:
        candidates = [
            {
                "candidate_id": "C-1",
                "type": "result",
                "source_unit_ids": ["U-1"],
                "content": "Tool Calling allows Gemini to decide how many lines to retrieve.",
                "importance": 1.0,
                "confidence": 0.95,
                "rationale": "",
                "related_topics": ["tool calling"],
                "extraction_scope": "B-001",
                "segment_ids": ["S-1"],
                "evidence_lines": [1],
                "evidence_quote": "Gemini can decide how many lines to retrieve.",
                "support_score": 0.9,
                "grounding_note": "grounded",
            },
            {
                "candidate_id": "C-2",
                "type": "result",
                "source_unit_ids": ["U-1"],
                "content": "Gemini can decide how many transcript lines to retrieve.",
                "importance": 1.0,
                "confidence": 0.95,
                "rationale": "",
                "related_topics": ["tool calling"],
                "extraction_scope": "B-001",
                "segment_ids": ["S-1"],
                "evidence_lines": [1],
                "evidence_quote": "Gemini can decide how many lines to retrieve.",
                "support_score": 0.9,
                "grounding_note": "grounded",
            },
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(len(memory_objects), 1)
        self.assertLessEqual(memory_objects[0]["importance"], 0.68)

    def test_reducer_conservatively_penalizes_uncertain_source_units(self) -> None:
        base = {
            "candidate_id": "C-1",
            "type": "method_change",
            "source_unit_ids": ["U-1"],
            "content": "The team decided to adopt tool calling as the long-term memory extraction pipeline.",
            "importance": 0.95,
            "confidence": 0.95,
            "rationale": "",
            "related_topics": ["tool calling", "long-term memory"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_lines": [1, 2, 3],
            "evidence_quote": "The team decided to adopt tool calling as the pipeline.",
            "support_score": 0.9,
            "grounding_note": "grounded",
        }
        _, clean_objects, _ = reduce_l1_patch([base], meeting_id="T")
        uncertain = {
            **base,
            "source_unit_completeness": ["partial"],
            "source_unit_uncertainty_notes": ["segment boundary may omit context"],
            "unit_quality_warnings": [
                "uncertain_source_unit",
                "source_unit_uncertainty_note",
            ],
        }
        _, uncertain_objects, _ = reduce_l1_patch([uncertain], meeting_id="T")

        self.assertLess(
            uncertain_objects[0]["importance"],
            clean_objects[0]["importance"],
        )
        self.assertLessEqual(uncertain_objects[0]["importance"], 0.82)

    def test_reducer_caps_near_threshold_grounding_importance(self) -> None:
        candidate = {
            "candidate_id": "C-1",
            "type": "decision",
            "source_unit_ids": ["U-1"],
            "content": "The team decided to keep comparing tool-calling extraction with the previous bridge.",
            "importance": 0.95,
            "confidence": 0.95,
            "rationale": "",
            "related_topics": ["tool calling", "bridge"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_lines": [20, 21],
            "evidence_quote": "We should compare tool calling with the old bridge.",
            "support_score": 0.17,
            "grounding_note": "near threshold local alignment",
            "source_unit_completeness": ["complete"],
            "unit_quality_warnings": ["near_threshold_grounding"],
        }

        _, memory_objects, quality_index = reduce_l1_patch([candidate], meeting_id="T")

        self.assertEqual(len(memory_objects), 1)
        self.assertLessEqual(memory_objects[0]["importance"], 0.62)
        meta = quality_index[memory_objects[0]["obj_id"]]
        self.assertEqual(meta["quality_level"], "weak")
        self.assertIn("near_threshold_grounding", meta["quality_warnings"])

    def test_reducer_reclassifies_non_action_todo_as_result(self) -> None:
        candidate = {
            "candidate_id": "C-1",
            "type": "todo",
            "source_unit_ids": ["U-1"],
            "content": (
                "It was concluded that the LLM behavior is adjustable through "
                "carefully crafted prompts."
            ),
            "importance": 0.9,
            "confidence": 0.92,
            "rationale": "",
            "related_topics": ["prompting"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_lines": [36, 37],
            "evidence_quote": "I think this is adjustable with the correct prompt.",
            "support_score": 0.82,
            "grounding_note": "grounded",
            "source_unit_completeness": ["complete"],
        }

        decision_candidate = {**candidate, "candidate_id": "C-2", "type": "decision"}
        _, memory_objects, _ = reduce_l1_patch(
            [candidate, decision_candidate],
            meeting_id="T",
        )

        self.assertEqual(len(memory_objects), 1)
        self.assertEqual(memory_objects[0]["type"], "result")

    def test_reducer_dedupes_result_argument_same_span(self) -> None:
        result_candidate = {
            "candidate_id": "C-result",
            "type": "result",
            "source_unit_ids": ["U-1"],
            "content": (
                "The iterative method is considered superior because it can "
                "capture overlapping ideas that fixed chunks miss."
            ),
            "importance": 0.78,
            "confidence": 0.9,
            "rationale": "",
            "related_topics": ["idea units"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_lines": [56, 57, 58],
            "evidence_quote": "It can look up and down and catch overlap.",
            "support_score": 0.76,
            "grounding_note": "grounded",
            "source_unit_completeness": ["complete"],
        }
        argument_candidate = {
            **result_candidate,
            "candidate_id": "C-argument",
            "type": "argument",
            "importance": 0.86,
        }

        _, memory_objects, _ = reduce_l1_patch(
            [result_candidate, argument_candidate],
            meeting_id="T",
        )

        self.assertEqual(len(memory_objects), 1)
        self.assertEqual(memory_objects[0]["type"], "argument")

    def test_reducer_emits_quality_sidecar_without_polluting_l1_schema(self) -> None:
        candidate = {
            "candidate_id": "C-1",
            "type": "method_change",
            "source_unit_ids": ["U-1"],
            "content": "The team decided to adopt tool calling for long-term memory extraction.",
            "importance": 0.92,
            "confidence": 0.95,
            "rationale": "",
            "related_topics": ["tool calling", "long-term memory"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_lines": [10, 11, 12],
            "evidence_quote": "We decided tool calling should be the memory extraction path.",
            "support_score": 0.86,
            "grounding_note": "grounded",
            "source_unit_completeness": ["complete"],
        }

        _, memory_objects, quality_index = reduce_l1_patch([candidate], meeting_id="T")

        self.assertEqual(
            set(memory_objects[0].keys()),
            {
                "obj_id",
                "type",
                "content",
                "importance",
                "evidence",
                "related_topics",
                "related_obj_ids",
            },
        )
        meta = quality_index[memory_objects[0]["obj_id"]]
        self.assertEqual(meta["quality_level"], "strong")
        self.assertEqual(meta["support_score"], 0.86)
        self.assertEqual(meta["evidence_lines"], [10, 11, 12])
        self.assertEqual(meta["source_candidate_ids"], ["C-1"])

    def test_reducer_reclassifies_evaluation_suggestion_as_todo(self) -> None:
        candidates = [
            {
                "candidate_id": "C-1",
                "type": "method_change",
                "source_unit_ids": ["U-1"],
                "content": "It is suggested to evaluate fixed-size versus sentence-by-sentence unit generation methods.",
                "importance": 1.0,
                "confidence": 0.95,
                "rationale": "",
                "related_topics": ["evaluation"],
                "extraction_scope": "B-001",
                "segment_ids": ["S-1"],
                "evidence_lines": [1, 2],
                "evidence_quote": "You should compare fixed-size and sentence-by-sentence methods.",
                "support_score": 0.9,
                "grounding_note": "grounded",
            }
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(memory_objects[0]["type"], "todo")
        self.assertLessEqual(memory_objects[0]["importance"], 0.88)

    def test_reducer_reclassifies_unresolved_decision_as_todo(self) -> None:
        candidates = [
            {
                "candidate_id": "C-1",
                "type": "decision",
                "source_unit_ids": ["U-1"],
                "content": "An unresolved task is to define how the Importance score should be calculated.",
                "importance": 0.9,
                "confidence": 0.95,
                "rationale": "",
                "related_topics": ["importance"],
                "extraction_scope": "B-001",
                "segment_ids": ["S-1"],
                "evidence_lines": [1, 2],
                "evidence_quote": "We still need to define importance.",
                "support_score": 0.9,
                "grounding_note": "grounded",
            }
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(memory_objects[0]["type"], "todo")

    def test_reducer_merges_todo_open_question_duplicate(self) -> None:
        base = {
            "source_unit_ids": ["U-1"],
            "importance": 0.85,
            "confidence": 0.95,
            "rationale": "",
            "related_topics": ["tool calling"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_lines": [1, 2, 3],
            "evidence_quote": "We need to define when tool calling triggers.",
            "support_score": 0.9,
            "grounding_note": "grounded",
        }
        candidates = [
            {
                **base,
                "candidate_id": "C-1",
                "type": "todo",
                "content": "需要定義在什麼節點狀態下會觸發 tool calling。",
            },
            {
                **base,
                "candidate_id": "C-2",
                "type": "open_question",
                "content": "在什麼節點狀態下會觸發 tool calling？",
            },
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(len(memory_objects), 1)
        self.assertEqual(memory_objects[0]["type"], "todo")

    def test_reducer_keeps_structure_description_as_result_not_todo(self) -> None:
        candidates = [
            {
                "candidate_id": "C-1",
                "type": "decision",
                "source_unit_ids": ["U-1"],
                "content": "The long-term memory object has a defined structure containing Type, Content, Evidence, and Related Topics.",
                "importance": 0.9,
                "confidence": 0.95,
                "rationale": "",
                "related_topics": ["memory"],
                "extraction_scope": "B-001",
                "segment_ids": ["S-1"],
                "evidence_lines": [1, 2, 3],
                "evidence_quote": "The object has Type, Content, Evidence, and Related Topics. Later we should compare baselines.",
                "support_score": 0.9,
                "grounding_note": "grounded",
            }
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(memory_objects[0]["type"], "result")

    def test_reducer_reclassifies_dataset_decision_as_decision(self) -> None:
        candidates = [
            {
                "candidate_id": "C-1",
                "type": "method_change",
                "source_unit_ids": ["U-1"],
                "content": "The team decided to use its own dataset for evaluation.",
                "importance": 0.85,
                "confidence": 0.95,
                "rationale": "",
                "related_topics": ["evaluation"],
                "extraction_scope": "B-001",
                "segment_ids": ["S-1"],
                "evidence_lines": [1, 2],
                "evidence_quote": "We can use our own dataset because it contains relevant method changes.",
                "support_score": 0.8,
                "grounding_note": "grounded",
            }
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(memory_objects[0]["type"], "decision")

    def test_reducer_reclassifies_uncommitted_method_proposal_as_result(self) -> None:
        candidates = [
            {
                "candidate_id": "C-1",
                "type": "method_change",
                "source_unit_ids": ["U-1"],
                "content": "A proposed method uses information entropy to predict the next chunk size.",
                "importance": 0.85,
                "confidence": 0.95,
                "rationale": "",
                "related_topics": ["segmentation"],
                "extraction_scope": "B-001",
                "segment_ids": ["S-1"],
                "evidence_lines": [1, 2],
                "evidence_quote": "One possible method is to use information entropy.",
                "support_score": 0.8,
                "grounding_note": "grounded",
            }
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(memory_objects[0]["type"], "result")

    def test_reducer_treats_chinese_adding_sentence_as_uncommitted_proposal(self) -> None:
        candidates = [
            {
                "candidate_id": "C-1",
                "type": "method_change",
                "source_unit_ids": ["U-1"],
                "content": "提出一種基於資訊熵的動態分段方法；新句子的加入若提高熵值，代表主題切換。",
                "importance": 0.95,
                "confidence": 0.95,
                "rationale": "",
                "related_topics": ["segmentation"],
                "extraction_scope": "B-001",
                "segment_ids": ["S-1"],
                "evidence_lines": [1, 2],
                "evidence_quote": "可以考慮用資訊熵看新句子的加入是否造成主題變化。",
                "support_score": 0.8,
                "grounding_note": "grounded",
            }
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(memory_objects[0]["type"], "result")
        self.assertLessEqual(memory_objects[0]["importance"], 0.86)

    def test_reducer_reclassifies_final_output_format_as_result(self) -> None:
        candidates = [
            {
                "candidate_id": "C-1",
                "type": "method_change",
                "source_unit_ids": ["U-1"],
                "content": "The final output of processing a transcription will be a collection of memory objects as defined in the long-term memory system.",
                "importance": 0.95,
                "confidence": 0.95,
                "rationale": "",
                "related_topics": ["memory object"],
                "extraction_scope": "B-001",
                "segment_ids": ["S-1"],
                "evidence_lines": [1, 2],
                "evidence_quote": "The final output is memory objects with Type, Content, Evidence, and Related Topics.",
                "support_score": 0.9,
                "grounding_note": "grounded",
            }
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(memory_objects[0]["type"], "result")
        self.assertLessEqual(memory_objects[0]["importance"], 0.88)

    def test_reducer_reclassifies_chinese_final_output_as_result(self) -> None:
        candidates = [
            {
                "candidate_id": "C-1",
                "type": "decision",
                "source_unit_ids": ["U-1"],
                "content": "處理轉錄稿的最終產出將是一組為長期記憶定義的 memory object。",
                "importance": 0.95,
                "confidence": 0.95,
                "rationale": "",
                "related_topics": ["memory object"],
                "extraction_scope": "B-001",
                "segment_ids": ["S-1"],
                "evidence_lines": [1, 2],
                "evidence_quote": "最後產出就是 long-term memory object。",
                "support_score": 0.9,
                "grounding_note": "grounded",
            }
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(memory_objects[0]["type"], "result")

    def test_reducer_reclassifies_descriptive_todo_as_result(self) -> None:
        candidates = [
            {
                "candidate_id": "C-1",
                "type": "todo",
                "source_unit_ids": ["U-1"],
                "content": "長期記憶被組織成 L1、L2、L3 三層級結構，並在命中 L1 時一併提供 L2 和 L3 摘要。",
                "importance": 0.9,
                "confidence": 0.95,
                "rationale": "",
                "related_topics": ["long-term memory"],
                "extraction_scope": "B-001",
                "segment_ids": ["S-1"],
                "evidence_lines": [1, 2],
                "evidence_quote": "Long-term memory has L1, L2, and L3.",
                "support_score": 0.9,
                "grounding_note": "grounded",
            }
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(memory_objects[0]["type"], "result")

    def test_reducer_reclassifies_uncommitted_decision_proposal_as_result(self) -> None:
        candidates = [
            {
                "candidate_id": "C-1",
                "type": "decision",
                "source_unit_ids": ["U-1"],
                "content": "提議一個新的記憶更新流程：先將傳入的想法分類為短期或長期。",
                "importance": 0.9,
                "confidence": 0.95,
                "rationale": "",
                "related_topics": ["memory update"],
                "extraction_scope": "B-001",
                "segment_ids": ["S-1"],
                "evidence_lines": [1, 2],
                "evidence_quote": "Could first classify ideas as short-term or long-term.",
                "support_score": 0.9,
                "grounding_note": "grounded",
            }
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(memory_objects[0]["type"], "result")

    def test_reducer_merges_concept_duplicate_across_languages(self) -> None:
        base = {
            "source_unit_ids": ["U-1"],
            "importance": 0.95,
            "confidence": 0.95,
            "rationale": "",
            "related_topics": ["tool calling"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_quote": "Gemini uses Read and Write functions for the memory database.",
            "support_score": 0.9,
            "grounding_note": "grounded",
        }
        candidates = [
            {
                **base,
                "candidate_id": "C-1",
                "type": "decision",
                "content": "專案採用 Tool Calling，讓 Gemini 動態讀取逐字稿行數。",
                "evidence_lines": [1, 2],
            },
            {
                **base,
                "candidate_id": "C-2",
                "type": "method_change",
                "content": "The project uses Tool Calling with `Read` and `Write` functions to update the memory database.",
                "evidence_lines": [1, 2, 11, 12, 13],
            },
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(len(memory_objects), 1)
        self.assertEqual(memory_objects[0]["type"], "method_change")

    def test_reducer_caps_low_support_high_model_importance(self) -> None:
        candidates = [
            {
                "candidate_id": "C-1",
                "type": "decision",
                "source_unit_ids": ["U-1"],
                "content": "決定採用新的長期記憶展示策略。",
                "importance": 1.0,
                "confidence": 1.0,
                "rationale": "",
                "related_topics": ["demo"],
                "extraction_scope": "B-001",
                "segment_ids": ["S-1"],
                "evidence_lines": [1, 2, 3],
                "evidence_quote": "我們可以考慮展示策略。",
                "support_score": 0.2,
                "grounding_note": "grounded",
            }
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertLessEqual(memory_objects[0]["importance"], 0.86)

    def test_reducer_caps_goal_statement_importance(self) -> None:
        candidates = [
            {
                "candidate_id": "C-1",
                "type": "decision",
                "source_unit_ids": ["U-1"],
                "content": "The current goal for the long-term memory tree is to make it as flat as possible.",
                "importance": 1.0,
                "confidence": 1.0,
                "rationale": "",
                "related_topics": ["long-term memory"],
                "extraction_scope": "B-001",
                "segment_ids": ["S-1"],
                "evidence_lines": [1, 2, 3],
                "evidence_quote": "We want the tree to stay flat.",
                "support_score": 1.0,
                "grounding_note": "grounded",
            }
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertLessEqual(memory_objects[0]["importance"], 0.87)

    def test_reducer_does_not_boost_consecutive_viewpoint_mentions(self) -> None:
        patch, memory_objects, _ = reduce_l1_patch(
            [
                {
                    "candidate_id": "C-1",
                    "type": "method_change",
                    "source_unit_ids": ["U-1"],
                    "content": "The memory architecture will implement a forgetting mechanism where relevance decays over time if not revisited.",
                    "importance": 0.65,
                    "confidence": 0.9,
                    "rationale": "",
                    "related_topics": ["forgetting mechanism"],
                    "extraction_scope": "B-001",
                    "segment_ids": ["S-1"],
                    "evidence_lines": [10, 11, 12, 13, 14],
                    "evidence_quote": "The same forgetting mechanism is discussed in consecutive lines.",
                    "support_score": 0.9,
                    "grounding_note": "grounded",
                }
            ],
            meeting_id="T",
        )

        self.assertEqual(patch["viewpoint_recurrence"], [])
        self.assertNotIn("viewpoint_recurrence", memory_objects[0])

    def test_reducer_boosts_separated_viewpoint_episodes(self) -> None:
        base_candidate = {
            "candidate_id": "C-1",
            "type": "method_change",
            "source_unit_ids": ["U-1"],
            "content": "The memory architecture will implement a forgetting mechanism where relevance decays over time if not revisited.",
            "importance": 0.65,
            "confidence": 0.9,
            "rationale": "",
            "related_topics": ["forgetting mechanism"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_quote": "The forgetting mechanism returns in separated meeting moments.",
            "support_score": 0.9,
            "grounding_note": "grounded",
        }
        _, consecutive_objects, _ = reduce_l1_patch(
            [{**base_candidate, "evidence_lines": [10, 11, 12, 13, 14]}],
            meeting_id="T",
        )
        separated_patch, separated_objects, _ = reduce_l1_patch(
            [{**base_candidate, "evidence_lines": [10, 11, 30, 31, 50]}],
            meeting_id="T",
        )

        self.assertGreater(
            separated_objects[0]["importance"],
            consecutive_objects[0]["importance"],
        )
        self.assertEqual(
            separated_patch["viewpoint_recurrence"][0]["viewpoint_key"],
            "long_term_forgetting_decay",
        )
        self.assertEqual(separated_patch["viewpoint_recurrence"][0]["episode_count"], 3)
        self.assertEqual(separated_patch["viewpoint_recurrence"][0]["bonus"], 0.04)
        self.assertEqual(
            separated_patch["viewpoint_recurrence"][0]["affected_objects"][0]["base_importance"],
            consecutive_objects[0]["importance"],
        )
        self.assertEqual(
            separated_patch["viewpoint_recurrence"][0]["affected_objects"][0]["adjusted_importance"],
            separated_objects[0]["importance"],
        )

    def test_reducer_merges_demo_dataset_synonyms(self) -> None:
        base = {
            "type": "decision",
            "source_unit_ids": ["U-1"],
            "importance": 0.9,
            "confidence": 0.95,
            "rationale": "",
            "related_topics": ["demo"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_quote": "Use our meeting transcripts for the project demo.",
            "support_score": 0.9,
            "grounding_note": "grounded",
        }
        candidates = [
            {
                **base,
                "candidate_id": "C-1",
                "content": "團隊決定使用自身的會議紀錄作為評估和專案演示的資料集。",
                "evidence_lines": [157, 158],
            },
            {
                **base,
                "candidate_id": "C-2",
                "content": "The evaluation and demonstration strategy will use the team's own meeting transcripts as the primary dataset.",
                "evidence_lines": [169, 170, 171],
            },
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(len(memory_objects), 1)

    def test_reducer_merges_hyphenated_tool_calling_concept(self) -> None:
        base = {
            "importance": 0.9,
            "confidence": 0.95,
            "rationale": "",
            "related_topics": ["tool calling"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_quote": "Tool-calling dynamically adjusts chunk size.",
            "support_score": 0.9,
            "grounding_note": "grounded",
        }
        candidates = [
            {
                **base,
                "candidate_id": "C-1",
                "type": "method_change",
                "source_unit_ids": ["U-1"],
                "content": "The transcript analysis method changed to an iterative, non-sequential tool-calling process that dynamically determines chunk size.",
                "evidence_lines": [45, 46, 47],
            },
            {
                **base,
                "candidate_id": "C-2",
                "type": "decision",
                "source_unit_ids": ["U-2"],
                "content": "系統將採用動態分塊機制，透過 Function Calling 的 Read 函式自行決定逐字稿行數。",
                "evidence_lines": [55, 56, 57],
            },
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(len(memory_objects), 1)
        self.assertEqual(memory_objects[0]["type"], "method_change")

    def test_reducer_preserves_read_write_content_when_merging(self) -> None:
        base = {
            "importance": 0.9,
            "confidence": 0.95,
            "rationale": "",
            "related_topics": ["tool calling"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "support_score": 0.9,
            "grounding_note": "grounded",
        }
        candidates = [
            {
                **base,
                "candidate_id": "C-1",
                "type": "decision",
                "source_unit_ids": ["U-1"],
                "content": "The memory update architecture uses Tool Calling with `Read` and `Write` functions for transcript line chunks and the memory database.",
                "evidence_lines": [1, 2],
                "evidence_quote": "Gemini has Read and Write functions.",
            },
            {
                **base,
                "candidate_id": "C-2",
                "type": "method_change",
                "source_unit_ids": ["U-2"],
                "content": "The transcript analysis method changed to an iterative tool-calling process that adjusts chunk size.",
                "evidence_lines": [3, 4],
                "evidence_quote": "Tool calling is iterative.",
            },
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(len(memory_objects), 1)
        self.assertIn("Read", memory_objects[0]["content"])
        self.assertIn("Write", memory_objects[0]["content"])

    def test_reducer_uses_best_duplicate_target_not_first_match(self) -> None:
        base = {
            "source_unit_ids": ["U-1"],
            "importance": 0.9,
            "confidence": 0.95,
            "rationale": "",
            "related_topics": ["tool calling", "memory database"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_quote": "Gemini uses Read and Write functions for memory update.",
            "support_score": 0.9,
            "grounding_note": "grounded",
        }
        candidates = [
            {
                **base,
                "candidate_id": "C-1",
                "type": "argument",
                "content": "Tool calling is useful because Gemini can dynamically decide transcript line chunks.",
                "evidence_lines": [1, 2, 3, 4, 5, 6, 7, 8],
            },
            {
                **base,
                "candidate_id": "C-2",
                "type": "method_change",
                "content": "記憶體更新流程是透過提供 Gemini 兩個主要函式 `Read` 和 `Write` 來實現。",
                "evidence_lines": [11, 12, 13],
            },
            {
                **base,
                "candidate_id": "C-3",
                "type": "result",
                "content": "記憶體更新流程透過提供 `Read` 和 `Write` 兩個主要函式給 Gemini 來實現。",
                "evidence_lines": [11, 12, 13],
            },
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        contents = [obj["content"] for obj in memory_objects]
        self.assertEqual(len(memory_objects), 2)
        self.assertEqual(
            sum("Read" in content and "Write" in content for content in contents),
            1,
        )

    def test_reducer_merges_same_type_read_write_paraphrase(self) -> None:
        base = {
            "type": "method_change",
            "source_unit_ids": ["U-1"],
            "importance": 0.9,
            "confidence": 0.95,
            "rationale": "",
            "related_topics": ["tool calling", "memory database"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_lines": [1, 2, 3],
            "evidence_quote": "Gemini uses Read and Write functions to update memory.",
            "support_score": 0.9,
            "grounding_note": "grounded",
        }
        candidates = [
            {
                **base,
                "candidate_id": "C-1",
                "content": "記憶體更新流程透過提供 `Read` 和 `Write` 函式給 Gemini 來實現。",
            },
            {
                **base,
                "candidate_id": "C-2",
                "content": "記憶體更新流程是透過 Gemini 的 `Read` 與 `Write` 兩個主要函式來實現。",
            },
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(len(memory_objects), 1)
        self.assertEqual(memory_objects[0]["type"], "method_change")

    def test_reducer_merges_flat_memory_tree_goal(self) -> None:
        base = {
            "importance": 0.9,
            "confidence": 0.95,
            "rationale": "",
            "related_topics": ["long-term memory"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_quote": "The long-term memory tree should stay flat.",
            "support_score": 0.9,
            "grounding_note": "grounded",
        }
        candidates = [
            {
                **base,
                "candidate_id": "C-1",
                "type": "decision",
                "source_unit_ids": ["U-1"],
                "content": "當前長期記憶樹的目標是使其盡可能扁平化。",
                "evidence_lines": [140, 141],
            },
            {
                **base,
                "candidate_id": "C-2",
                "type": "result",
                "source_unit_ids": ["U-2"],
                "content": "The current goal for the long-term memory tree is to make it as flat as possible.",
                "evidence_lines": [141],
            },
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(len(memory_objects), 1)
        self.assertLessEqual(memory_objects[0]["importance"], 0.87)

    def test_reducer_merges_same_type_high_evidence_overlap(self) -> None:
        base = {
            "type": "todo",
            "source_unit_ids": ["U-1"],
            "importance": 0.9,
            "confidence": 0.95,
            "rationale": "",
            "related_topics": ["evaluation"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_lines": [1, 2, 3, 4],
            "evidence_quote": "Compare fixed-size and sentence-by-sentence baselines.",
            "support_score": 0.9,
            "grounding_note": "grounded",
        }
        candidates = [
            {
                **base,
                "candidate_id": "C-1",
                "content": "Compare the new unit generation method against fixed-size and sentence-by-sentence baselines.",
            },
            {
                **base,
                "candidate_id": "C-2",
                "content": "在截止日前，應將新的單元生成方法與固定大小分塊和逐句分塊進行比較。",
            },
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(len(memory_objects), 1)
        self.assertEqual(memory_objects[0]["type"], "todo")

    def test_reducer_merges_decision_method_change_same_evidence(self) -> None:
        base = {
            "source_unit_ids": ["U-1"],
            "importance": 0.9,
            "confidence": 0.95,
            "rationale": "",
            "related_topics": ["tool calling"],
            "extraction_scope": "B-001",
            "segment_ids": ["S-1"],
            "evidence_lines": [1, 2, 3, 4],
            "evidence_quote": "The project will adopt dynamic tool calling.",
            "support_score": 0.9,
            "grounding_note": "grounded",
        }
        candidates = [
            {
                **base,
                "candidate_id": "C-1",
                "type": "decision",
                "content": "The project will adopt dynamic tool calling.",
            },
            {
                **base,
                "candidate_id": "C-2",
                "type": "method_change",
                "content": "專案採用動態 tool calling 方法。",
            },
        ]

        _, memory_objects, _ = reduce_l1_patch(candidates, meeting_id="T")

        self.assertEqual(len(memory_objects), 1)
        self.assertEqual(memory_objects[0]["type"], "method_change")

    def test_conflict_resolver_merges_redundant_cross_type_candidate(self) -> None:
        base = {
            "source_unit_ids": ["U-1"],
            "content": "改用 per-student recall 作為評估方式。",
            "importance": 0.7,
            "confidence": 0.8,
            "rationale": "",
            "related_topics": ["evaluation"],
            "evidence_lines": [1],
            "evidence_quote": "We switched evaluation to per-student recall.",
            "support_score": 0.8,
            "grounding_note": "grounded",
            "source_unit_completeness": ["partial"],
            "source_unit_uncertainty_notes": ["needs previous context"],
        }
        candidates = [
            GroundedCandidate(
                candidate_id="C-decision-001",
                type="decision",
                extraction_scope="B-001",
                segment_ids=["S-1"],
                **base,
            ),
            GroundedCandidate(
                candidate_id="C-method_change-001",
                type="method_change",
                extraction_scope="B-001",
                segment_ids=["S-1"],
                **base,
            ),
        ]

        resolved, decisions = resolve_cross_type_conflicts(candidates)

        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["type"], "method_change")
        self.assertEqual(resolved[0]["source_unit_completeness"], ["partial"])
        self.assertEqual(resolved[0]["source_unit_uncertainty_notes"], ["needs previous context"])
        self.assertTrue(any(decision.action == "merge" for decision in decisions))

    def test_verifier_rejects_out_of_bounds_evidence(self) -> None:
        result = verify_l1_candidates(
            [
                {
                    "candidate_id": "C-result-001",
                    "type": "result",
                    "content": "模型輸出改善。",
                    "importance": 0.6,
                    "evidence_lines": [99],
                    "evidence_quote": "improved",
                    "support_score": 0.7,
                }
            ],
            max_line=3,
        )

        self.assertEqual(len(result.verified_candidates), 0)
        self.assertEqual(len(result.rejected_candidates), 1)
        self.assertIn(
            "evidence_out_of_bounds",
            result.rejected_candidates[0]["verification_reasons"],
        )

    def test_reduce_patch_preserves_l1_tree_schema(self) -> None:
        patch, memory_objects, _ = reduce_l1_patch(
            [
                {
                    "candidate_id": "C-result-001",
                    "type": "result",
                    "content": "模型輸出改善。",
                    "importance": 0.7,
                    "evidence_quote": "The output improved.",
                    "related_topics": ["model"],
                }
            ],
            meeting_id="Unit001",
        )

        self.assertEqual(patch["operation"], "replace_meeting_l1")
        self.assertEqual(memory_objects[0]["obj_id"], "L1-Unit001-001")
        self.assertEqual(
            sorted(memory_objects[0].keys()),
            [
                "content",
                "evidence",
                "importance",
                "obj_id",
                "related_obj_ids",
                "related_topics",
                "type",
            ],
        )


if __name__ == "__main__":
    unittest.main()
