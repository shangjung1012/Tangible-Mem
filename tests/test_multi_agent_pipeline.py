from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
sys.path.insert(0, str(LONG_TERM_DIR))

from multi_agent_agents import l1_type_agent  # noqa: E402
from multi_agent_pipeline import build_continuation_batches, idea_units_for_batch  # noqa: E402
from multi_agent_reducer import (  # noqa: E402
    reduce_l1_patch,
    resolve_cross_type_conflicts,
)
from multi_agent_state import (  # noqa: E402
    GroundedCandidate,
    IdeaUnit,
    L1Candidate,
    SegmentProposal,
    parse_transcript_lines,
)
from multi_agent_verifier import ground_candidates, verify_l1_candidates  # noqa: E402


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


class MultiAgentPipelineTests(unittest.TestCase):
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
        patch, memory_objects = reduce_l1_patch(
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
