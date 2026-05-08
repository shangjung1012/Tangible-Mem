from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from share_mem.build_tree import _run_bridge_for_transcript, parse_args
from share_mem.compare_l1_runs import compare_l1_trees, iter_l1_objects, write_comparison_outputs
from share_mem.l1.multi_agent_agents import l1_type_agent
from share_mem.l1.multi_agent_logger import ResearchLogger
from share_mem.l1.multi_agent_reducer import reduce_l1_patch
from share_mem.l1.multi_agent_state import IdeaUnit
from share_mem.l1.taxonomy import (
    LEGACY_L1_TYPES,
    V2_MEMORY_ROLE_TYPES,
    candidate_schema_for_taxonomy,
)


def _candidate(
    *,
    candidate_id: str = "C-001",
    obj_type: str,
    legacy_type: str,
    content: str = "The team proposed using a side-by-side taxonomy experiment.",
    importance: float = 0.76,
    evidence_lines: list[int] | None = None,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "type": obj_type,
        "legacy_type": legacy_type,
        "source_unit_ids": ["U-1"],
        "content": content,
        "importance": importance,
        "confidence": 0.9,
        "rationale": "bounded evidence supports the candidate",
        "related_topics": ["taxonomy", "memory roles"],
        "extraction_scope": "B-001",
        "segment_ids": ["S-001"],
        "evidence_lines": evidence_lines or [1, 2],
        "evidence_quote": "The team proposed using a side-by-side taxonomy experiment.",
        "support_score": 0.82,
        "grounding_note": "local evidence-content alignment",
        "source_unit_completeness": ["complete"],
        "source_unit_uncertainty_notes": [],
        "verification_reasons": [],
        "content_tokens": ["taxonomy"],
    }


class _PromptCaptureRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def call_json(self, stage: str, prompt: str, schema: dict) -> dict:
        self.calls.append((stage, prompt))
        return {
            "candidates": [
                {
                    "type": "finding",
                    "legacy_type": "result",
                    "source_unit_ids": ["U-1"],
                    "content": "The future demo does not need to operate in real time.",
                    "importance": 0.72,
                    "confidence": 0.86,
                    "rationale": "The bounded unit resolves a demo requirement.",
                    "related_topics": ["demo workflow"],
                }
            ]
        }


class L1TypeV2ExperimentTests(unittest.TestCase):
    def test_v1_candidate_schema_does_not_require_legacy_type_by_default(self) -> None:
        schema = candidate_schema_for_taxonomy("v1")
        candidate_schema = schema["properties"]["candidates"]["items"]

        self.assertNotIn("type", candidate_schema["properties"])
        self.assertNotIn("legacy_type", candidate_schema["properties"])
        self.assertNotIn("legacy_type", candidate_schema["required"])

    def test_v2_candidate_schema_requires_legacy_type(self) -> None:
        schema = candidate_schema_for_taxonomy(
            "v2-memory-roles",
            include_legacy_type=True,
        )
        candidate_schema = schema["properties"]["candidates"]["items"]

        self.assertEqual(
            candidate_schema["properties"]["type"]["enum"],
            sorted(V2_MEMORY_ROLE_TYPES),
        )
        self.assertEqual(
            candidate_schema["properties"]["legacy_type"]["enum"],
            sorted(LEGACY_L1_TYPES),
        )
        self.assertIn("legacy_type", candidate_schema["required"])

    def test_v2_type_agent_prompt_preserves_demo_scope_clarifications(self) -> None:
        runner = _PromptCaptureRunner()
        units = [
            IdeaUnit(
                unit_id="U-1",
                segment_id="S-1",
                line_start=81,
                line_end=82,
                text=(
                    "Future demo 是否需要 real time? "
                    "Answer: 不一定要 real time; this is about memory update and later usage."
                ),
                completeness="complete",
            )
        ]

        candidates = l1_type_agent(
            runner,
            obj_type="finding",
            idea_units=units,
            existing_topics=[],
            extraction_scope="B-001",
            segment_ids=["S-1"],
            taxonomy="v2-memory-roles",
            include_legacy_type=True,
        )

        prompt = runner.calls[0][1]
        self.assertIn("requirement/scope clarifications", prompt)
        self.assertIn("real-time", prompt)
        self.assertEqual(candidates[0].type, "finding")
        self.assertEqual(candidates[0].legacy_type, "result")

    def test_v2_type_agent_prompt_preserves_l1_discard_and_importance_usage_questions(self) -> None:
        runner = _PromptCaptureRunner()
        units = [
            IdeaUnit(
                unit_id="U-1",
                segment_id="S-1",
                line_start=120,
                line_end=124,
                text=(
                    "What does discard as L1 mean? I thought every processed unit becomes an L1. "
                    "We still need to inspect how the code uses the importance score."
                ),
                completeness="complete",
            )
        ]

        l1_type_agent(
            runner,
            obj_type="open_issue",
            idea_units=units,
            existing_topics=[],
            extraction_scope="B-001",
            segment_ids=["S-1"],
            taxonomy="v2-memory-roles",
            include_legacy_type=True,
        )

        prompt = runner.calls[0][1]
        self.assertIn("discard as L1", prompt)
        self.assertIn("importance score is used", prompt)
        self.assertIn("open_issue", prompt)

    def test_reduce_v2_patch_preserves_type_and_legacy_type(self) -> None:
        _, memory_objects, quality_index = reduce_l1_patch(
            [
                _candidate(
                    obj_type="proposal",
                    legacy_type="result",
                    content="The team proposed adding a proposal role before adopting it.",
                )
            ],
            meeting_id="T",
            taxonomy="v2-memory-roles",
            include_legacy_type=True,
        )

        self.assertEqual(memory_objects[0]["type"], "proposal")
        self.assertEqual(memory_objects[0]["legacy_type"], "result")
        self.assertEqual(quality_index["L1-T-001"]["type"], "proposal")
        self.assertEqual(quality_index["L1-T-001"]["legacy_type"], "result")

    def test_reduce_v2_patch_merges_exact_cross_type_duplicates(self) -> None:
        content = (
            "The same-meeting merge rule has a flaw: identical evidence can survive as "
            "both an open issue and a finding."
        )

        _, memory_objects, _ = reduce_l1_patch(
            [
                _candidate(
                    candidate_id="C-open-issue",
                    obj_type="open_issue",
                    legacy_type="open_question",
                    content=content,
                    importance=0.72,
                    evidence_lines=[10, 11],
                ),
                _candidate(
                    candidate_id="C-finding",
                    obj_type="finding",
                    legacy_type="result",
                    content=content,
                    importance=0.70,
                    evidence_lines=[10, 11],
                ),
            ],
            meeting_id="T",
            taxonomy="v2-memory-roles",
            include_legacy_type=True,
        )

        self.assertEqual(len(memory_objects), 1)
        self.assertIn(memory_objects[0]["type"], {"finding", "open_issue"})

    def test_reduce_v2_reclassifies_considered_approach_change_as_proposal(self) -> None:
        content = (
            "A time-based memory architecture is being considered as an alternative, "
            "where each meeting creates a separate node and links are inferred later."
        )

        _, memory_objects, _ = reduce_l1_patch(
            [
                _candidate(
                    obj_type="approach_change",
                    legacy_type="method_change",
                    content=content,
                    importance=0.82,
                )
            ],
            meeting_id="T",
            taxonomy="v2-memory-roles",
            include_legacy_type=True,
        )

        self.assertEqual(memory_objects[0]["type"], "proposal")

    def test_build_tree_accepts_v2_taxonomy_flags(self) -> None:
        args = parse_args(
            [
                "--taxonomy",
                "v2-memory-roles",
                "--include-legacy-type",
                "--output-root",
                "share_mem_experiments/type_v2_legacy_test",
            ]
        )

        self.assertEqual(args.taxonomy, "v2-memory-roles")
        self.assertTrue(args.include_legacy_type)
        self.assertIn("share_mem_experiments", args.output_root)

    def test_bridge_invocation_passes_taxonomy_flags(self) -> None:
        with patch("share_mem.l1.bridge.main") as bridge_main:
            _run_bridge_for_transcript(
                transcript_path=Path("meeting_recording/transcript/grace/0506.txt"),
                tree_path=Path("share_mem_experiments/type_v2/tree.json"),
                snapshot_dir=Path("share_mem_experiments/type_v2/snapshots"),
                research_log_dir=Path("share_mem_experiments/type_v2/research_logs"),
                dataset_profile="grace",
                model="gemini-2.5-pro",
                taxonomy="v2-memory-roles",
                include_legacy_type=True,
            )

        bridge_args = bridge_main.call_args.args[0]
        self.assertIn("--taxonomy", bridge_args)
        self.assertIn("v2-memory-roles", bridge_args)
        self.assertIn("--include-legacy-type", bridge_args)

    def test_research_logger_writes_structured_api_call_debug_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logger = ResearchLogger(Path(tmp), "run-001")

            logger.write_api_call(
                stage="l1_proposal_agent:B-001",
                attempt=1,
                model="gemini-2.5-pro",
                config={"temperature": 0.1},
                schema={"type": "object"},
                prompt="PROMPT",
                raw_response='{"candidates":[]}',
                parsed_json={"candidates": []},
                latency_sec=1.25,
                success=True,
                error=None,
            )

            call_file = logger.run_dir / "api_calls" / "001_l1_proposal_agent_B-001_attempt1.json"
            jsonl_file = logger.run_dir / "api_calls" / "api_calls.jsonl"
            self.assertTrue(call_file.exists())
            self.assertTrue(jsonl_file.exists())
            payload = json.loads(call_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["stage"], "l1_proposal_agent:B-001")
            self.assertEqual(payload["prompt"], "PROMPT")
            self.assertEqual(payload["raw_response"], '{"candidates":[]}')
            self.assertEqual(payload["parsed_json"], {"candidates": []})
            self.assertTrue(payload["success"])

    def test_research_logger_writes_structured_api_call_error_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logger = ResearchLogger(Path(tmp), "run-001")

            logger.write_api_call(
                stage="l1_finding_agent:B-002",
                attempt=2,
                model="gemini-2.5-pro",
                config={"temperature": 0.1},
                schema={"type": "object"},
                prompt="PROMPT",
                raw_response="partial response",
                parsed_json=None,
                latency_sec=0.33,
                success=False,
                error={"type": "RuntimeError", "message": "boom"},
            )

            call_file = logger.run_dir / "api_calls" / "001_l1_finding_agent_B-002_attempt2.json"
            payload = json.loads(call_file.read_text(encoding="utf-8"))
            self.assertFalse(payload["success"])
            self.assertEqual(payload["error"]["type"], "RuntimeError")
            self.assertEqual(payload["prompt"], "PROMPT")
            self.assertEqual(payload["raw_response"], "partial response")

    def test_compare_l1_runs_reports_high_importance_missing_objects(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "old-1",
                            "type": "todo",
                            "content": "Build the share memory experiment runner.",
                            "importance": 0.82,
                            "evidence": "Build the share memory experiment runner.",
                            "related_topics": ["share_mem"],
                        },
                        {
                            "obj_id": "old-2",
                            "type": "decision",
                            "content": "Adopt a canonical L1 store.",
                            "importance": 0.91,
                            "evidence": "Adopt a canonical L1 store.",
                            "related_topics": ["share_mem"],
                        },
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "new-1",
                            "type": "action_item",
                            "legacy_type": "todo",
                            "content": "Build the share memory experiment runner.",
                            "importance": 0.80,
                            "evidence": "Build the share memory experiment runner.",
                            "related_topics": ["share_mem"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["baseline_object_count"], 2)
        self.assertEqual(report["summary"]["candidate_object_count"], 1)
        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 1)
        self.assertEqual(report["manual_review_queue"][0]["baseline_obj_id"], "old-2")

    def test_compare_l1_runs_surfaces_possible_semantic_coverage(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "old-merge-rule",
                            "type": "decision",
                            "content": (
                                "The report appendix should include the evaluation table, "
                                "error analysis notes, and final comparison summary."
                            ),
                            "importance": 0.92,
                            "evidence": (
                                "The appendix needs the evaluation table and error analysis "
                                "notes before the final comparison summary."
                            ),
                            "related_topics": ["report appendix"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "new-merge-rule",
                            "type": "decision",
                            "legacy_type": "decision",
                            "content": (
                                "The appendix update adds the evaluation table and the "
                                "error-analysis notes, then closes with the comparison summary."
                            ),
                            "importance": 0.88,
                            "evidence": (
                                "Add the evaluation table, include error analysis notes, and "
                                "close the appendix with the comparison summary."
                            ),
                            "related_topics": ["appendix update"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(
            baseline,
            candidate,
            high_importance_threshold=0.7,
            match_threshold=0.90,
        )

        queue_item = report["manual_review_queue"][0]
        self.assertTrue(queue_item["possible_semantic_coverage"])
        self.assertEqual(queue_item["best_candidate"]["obj_id"], "new-merge-rule")

    def test_compare_l1_runs_matches_cross_lingual_taxonomy_coverage(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "old-taxonomy",
                            "type": "method_change",
                            "content": (
                                "Idea units are classified into six types to guide their "
                                "processing into the memory structure: Decision, To-Do, "
                                "Method Change, Result, Argument, and Open Question."
                            ),
                            "importance": 0.76,
                            "evidence": (
                                "unit 可以被標籤某一種 type。六個 type agents 是 "
                                "Method Change, To-Do, Result, Argument, Open Question, "
                                "Decision。"
                            ),
                            "related_topics": ["L1 taxonomy", "memory update"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "new-taxonomy",
                            "type": "decision",
                            "legacy_type": "decision",
                            "content": (
                                "系統處理資訊時，首先識別 idea units。接著代理人會為這些"
                                "單元分配六個預定義標籤之一：方法變更、待辦事項、結果、"
                                "論點、開放問題、決策。"
                            ),
                            "importance": 0.72,
                            "evidence": (
                                "代理人會為 idea units 分配六個預定義標籤之一："
                                "Method Change, To-Do, Result, Argument, Open Question, "
                                "Decision。"
                            ),
                            "related_topics": ["memory taxonomy", "memory update"],
                        },
                        {
                            "obj_id": "new-visualization",
                            "type": "decision",
                            "legacy_type": "decision",
                            "content": (
                                "A dynamic visualization will be created to demonstrate how "
                                "the memory graph is constructed and updated as new "
                                "transcripts are processed."
                            ),
                            "importance": 0.78,
                            "evidence": (
                                "The memory graph visualization should show update behavior "
                                "as transcripts are processed."
                            ),
                            "related_topics": ["memory graph", "visualization"],
                        },
                    ],
                }
            ]
        }

        report = compare_l1_trees(
            baseline,
            candidate,
            high_importance_threshold=0.7,
        )

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 0)
        self.assertEqual(report["matches"][0]["candidate_obj_id"], "new-taxonomy")
        self.assertGreaterEqual(
            report["matches"][0]["score"]["semantic_anchor_similarity"],
            0.4,
        )

    def test_compare_l1_runs_matches_memory_retention_policy_paraphrase(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0307",
                    "memory_objects": [
                        {
                            "obj_id": "old-retention",
                            "type": "result",
                            "content": (
                                "The system implements a memory retention policy where an "
                                "item is automatically deleted if it is not discussed "
                                "within a window of three meetings."
                            ),
                            "importance": 0.73,
                            "evidence": (
                                "Use meeting IDs to track recency and delete a memory item "
                                "when it has not been discussed for three meetings."
                            ),
                            "related_topics": ["memory retention"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0307",
                    "memory_objects": [
                        {
                            "obj_id": "new-retention",
                            "type": "approach_change",
                            "legacy_type": "method_change",
                            "content": (
                                "系統將採用會議 ID 來表示記憶項目的時效性，並引入衰減"
                                "機制，刪除在三次會議內未被討論的項目。"
                            ),
                            "importance": 0.77,
                            "evidence": (
                                "meeting IDs track recency; delete the memory item if it "
                                "is not discussed for three meetings."
                            ),
                            "related_topics": ["memory decay mechanism"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 0)
        self.assertEqual(report["matches"][0]["candidate_obj_id"], "new-retention")

    def test_compare_l1_runs_matches_memo_rag_tradeoff_paraphrase(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0318",
                    "memory_objects": [
                        {
                            "obj_id": "old-memo",
                            "type": "decision",
                            "content": (
                                "The main claimed advantage of the MEMO system is lower "
                                "token consumption and reduced latency. However, it did "
                                "not outperform the RAG baseline on multi-hop questions."
                            ),
                            "importance": 0.80,
                            "evidence": (
                                "MEMO uses fewer tokens and has lower latency, but does "
                                "not beat RAG on multi-hop questions."
                            ),
                            "related_topics": ["MEMO", "RAG", "evaluation"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0318",
                    "memory_objects": [
                        {
                            "obj_id": "new-memo",
                            "type": "argument",
                            "legacy_type": "argument",
                            "content": (
                                "The MEMO model presents a trade-off: its main advantage "
                                "is low token consumption, but it does not outperform a "
                                "RAG-based approach on multi-hop questions."
                            ),
                            "importance": 0.74,
                            "evidence": (
                                "MEMO has low token consumption and latency; RAG still "
                                "performs better on multi-hop questions."
                            ),
                            "related_topics": ["memory evaluation", "RAG"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 0)
        self.assertEqual(report["matches"][0]["candidate_obj_id"], "new-memo")

    def test_compare_l1_runs_matches_external_db_forgetting_paraphrase(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0429",
                    "memory_objects": [
                        {
                            "obj_id": "old-forgetting",
                            "type": "decision",
                            "content": (
                                "The project will focus on forgetting at the external "
                                "database layer, similar to RAG, instead of changing "
                                "the LLM's internal model weights."
                            ),
                            "importance": 0.70,
                            "evidence": (
                                "Forgetting can be done by deleting data from the "
                                "database, like removing vectors from RAG storage."
                            ),
                            "related_topics": ["RAG", "memory forgetting"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0429",
                    "memory_objects": [
                        {
                            "obj_id": "new-forgetting",
                            "type": "argument",
                            "legacy_type": "argument",
                            "content": (
                                "There are two approaches to forgetting: delete data "
                                "from an external database like RAG, or alter LLM model "
                                "weights. The team postpones changing model weights."
                            ),
                            "importance": 0.76,
                            "evidence": (
                                "RAG stores vectors in a database; forgetting can be "
                                "implemented by deleting that data instead of changing "
                                "model weights."
                            ),
                            "related_topics": ["RAG", "research methodology"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 0)
        self.assertEqual(report["matches"][0]["candidate_obj_id"], "new-forgetting")

    def test_compare_l1_runs_matches_adaptive_segmentation_tradeoff_paraphrase(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "old-segmentation",
                            "type": "argument",
                            "content": (
                                "Adaptive segmentation was dismissed because imperfect "
                                "boundaries still require repair, and the downstream LLM "
                                "can process larger chunks."
                            ),
                            "importance": 0.72,
                            "evidence": (
                                "Even adaptive windows need boundary adjustment, while "
                                "the LLM can handle bigger chunks."
                            ),
                            "related_topics": ["segmentation", "boundary repair"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "new-segmentation",
                            "type": "finding",
                            "legacy_type": "result",
                            "content": (
                                "A high-precision adaptive window is not worth the "
                                "complexity: downstream LLMs tolerate less precise, "
                                "larger chunks and boundary adjustment is still needed."
                            ),
                            "importance": 0.69,
                            "evidence": (
                                "Adaptive segmentation still needs boundary repair; "
                                "larger chunks are acceptable for the LLM."
                            ),
                            "related_topics": ["data fragmentation", "segmentation"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 0)
        self.assertEqual(report["matches"][0]["candidate_obj_id"], "new-segmentation")

    def test_compare_l1_runs_accepts_same_meeting_high_content_evidence_overlap(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0422",
                    "memory_objects": [
                        {
                            "obj_id": "old-dynamic-eval",
                            "type": "todo",
                            "content": (
                                "Dynamic chunking should be evaluated against fixed-size "
                                "and sentence-by-sentence baselines, comparing accuracy, "
                                "processing time, and function call count."
                            ),
                            "importance": 0.78,
                            "evidence": (
                                "Compare dynamic chunking with fixed-size and "
                                "sentence-by-sentence chunking using accuracy, time, "
                                "and function calls."
                            ),
                            "related_topics": ["chunking evaluation"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0422",
                    "memory_objects": [
                        {
                            "obj_id": "new-dynamic-eval",
                            "type": "action_item",
                            "legacy_type": "todo",
                            "content": (
                                "Evaluate the dynamic chunking method with fixed-size "
                                "and sentence-level baselines; report the trade-off "
                                "between accuracy, runtime, and number of calls."
                            ),
                            "importance": 0.74,
                            "evidence": (
                                "The evaluation compares dynamic chunking to fixed-size "
                                "and sentence-by-sentence baselines on accuracy, time, "
                                "and function calls."
                            ),
                            "related_topics": ["model evaluation"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 0)
        self.assertEqual(report["matches"][0]["candidate_obj_id"], "new-dynamic-eval")

    def test_compare_l1_runs_matches_candidate_object_merge_mechanism(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0429",
                    "memory_objects": [
                        {
                            "obj_id": "old-candidate-object",
                            "type": "decision",
                            "content": (
                                "The create_object function first generates a candidate "
                                "object, then checks subsequent text and merges related "
                                "content into that candidate."
                            ),
                            "importance": 0.78,
                            "evidence": (
                                "Create an object as a candidate; later content is checked "
                                "for relation and merged when connected."
                            ),
                            "related_topics": ["candidate memory integration"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0429",
                    "memory_objects": [
                        {
                            "obj_id": "new-candidate-object",
                            "type": "decision",
                            "legacy_type": "decision",
                            "content": (
                                "To handle topics spanning chunks, the system stores a "
                                "potential topic as a candidate object and merges later "
                                "relevant content, preventing information loss."
                            ),
                            "importance": 0.72,
                            "evidence": (
                                "It first stores a candidate, checks whether later content "
                                "is related, and merges it for joint processing."
                            ),
                            "related_topics": ["long context processing", "candidate memory integration"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 0)
        self.assertEqual(report["matches"][0]["candidate_obj_id"], "new-candidate-object")

    def test_compare_l1_runs_matches_idea_unit_type_taxonomy_consolidation(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "old-taxonomy-consolidation",
                            "type": "method_change",
                            "content": (
                                "Idea units are classified into six types for memory "
                                "updates, and multiple agent proposals are consolidated "
                                "into one or two final labels."
                            ),
                            "importance": 0.76,
                            "evidence": (
                                "Idea units go through type agents; candidates are merged "
                                "so the final object has one or at most two labels."
                            ),
                            "related_topics": ["idea unit", "taxonomy"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "new-taxonomy-consolidation",
                            "type": "approach_change",
                            "legacy_type": "method_change",
                            "content": (
                                "The L1 pipeline sends idea units to typed agents, merges "
                                "duplicate candidates, and keeps the final memory object "
                                "to one primary type, with a second label only when needed."
                            ),
                            "importance": 0.71,
                            "evidence": (
                                "Idea units are sent to multiple type agents; duplicate "
                                "candidates are merged and final labels are constrained."
                            ),
                            "related_topics": ["L1 taxonomy", "memory update"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 0)
        self.assertEqual(
            report["matches"][0]["candidate_obj_id"],
            "new-taxonomy-consolidation",
        )

    def test_compare_l1_runs_matches_llm_as_judge_metric_consolidation(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0318",
                    "memory_objects": [
                        {
                            "obj_id": "old-llm-judge",
                            "type": "method_change",
                            "content": (
                                "A new evaluation method uses an LLM as a judge to "
                                "produce a binary correct/incorrect score, avoiding "
                                "semantic similarity metrics that can rate factually "
                                "wrong answers highly."
                            ),
                            "importance": 0.78,
                            "evidence": (
                                "The performance metric gives the answer to an LLM judge; "
                                "BERT-style semantic similarity can score Alice is seven "
                                "and Alice is three as similar even though the answer is wrong."
                            ),
                            "related_topics": ["evaluation strategy", "model evaluation"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0318",
                    "memory_objects": [
                        {
                            "obj_id": "new-llm-judge",
                            "type": "finding",
                            "legacy_type": "result",
                            "content": (
                                "The LOCOMO benchmark uses an LLM-as-judge binary "
                                "correct/incorrect evaluation averaged over ten runs to "
                                "avoid weaknesses of semantic similarity scores."
                            ),
                            "importance": 0.67,
                            "evidence": (
                                "It uses an LLM judge to mark answers correct or incorrect; "
                                "semantic scoring can be high for factually incorrect answers."
                            ),
                            "related_topics": ["LOCOMO benchmark", "evaluation metrics", "LLM-as-judge"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 0)
        self.assertEqual(report["matches"][0]["candidate_obj_id"], "new-llm-judge")

    def test_compare_l1_runs_matches_precision_recall_chunking_evaluation(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0429",
                    "memory_objects": [
                        {
                            "obj_id": "old-precision-recall",
                            "type": "method_change",
                            "content": (
                                "The chunking evaluation framework will use precision "
                                "and recall against human-annotated important idea units "
                                "as ground truth."
                            ),
                            "importance": 0.72,
                            "evidence": (
                                "Evaluate generated important idea units with precision "
                                "and recall compared with human-labeled important idea units."
                            ),
                            "related_topics": ["evaluation strategy", "benchmarking"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0429",
                    "memory_objects": [
                        {
                            "obj_id": "new-precision-recall",
                            "type": "finding",
                            "legacy_type": "result",
                            "content": (
                                "Generated chunks from different methods will be evaluated "
                                "using precision and recall against a ground truth of "
                                "human-annotated important idea units."
                            ),
                            "importance": 0.62,
                            "evidence": (
                                "The method compares important idea units with precision "
                                "and recall using human annotations as ground truth."
                            ),
                            "related_topics": ["evaluation methodology", "evaluation metrics"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 0)
        self.assertEqual(report["matches"][0]["candidate_obj_id"], "new-precision-recall")

    def test_compare_l1_runs_matches_importance_activation_parameter_separation(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "old-importance-activation",
                            "type": "method_change",
                            "content": (
                                "The memory system separates static importance from "
                                "dynamic activation. Importance is assigned at creation "
                                "as intrinsic value, while activation decays over time "
                                "to represent current accessibility."
                            ),
                            "importance": 0.76,
                            "evidence": (
                                "Importance should not be modified by decay because it "
                                "records original value; activation or recency handles "
                                "time decay."
                            ),
                            "related_topics": ["Memory Lifecycle", "Memory Representation"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "new-importance-activation",
                            "type": "approach_change",
                            "legacy_type": "method_change",
                            "content": (
                                "The memory schema defines importance as a static score "
                                "at creation, relevance as semantic similarity for retrieval, "
                                "and recency or activation as a dynamic time-decaying score."
                            ),
                            "importance": 0.89,
                            "evidence": (
                                "Importance is static; recency or activation decays over "
                                "time so the original importance value remains meaningful."
                            ),
                            "related_topics": ["importance score", "memory management"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 0)
        self.assertEqual(report["matches"][0]["candidate_obj_id"], "new-importance-activation")

    def test_compare_l1_runs_matches_low_lexical_importance_activation_translation(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "old-importance-activation-zh",
                            "type": "method_change",
                            "content": (
                                "Project notes mention a dataset and topic-tree context, "
                                "then define original significance separately from active access."
                            ),
                            "importance": 0.76,
                            "evidence": (
                                "The importance score should not be changed by decay; "
                                "activation or recency score represents how active the memory is now."
                            ),
                            "related_topics": [
                                "Memory Management",
                                "Memory Representation",
                                "Memory Lifecycle",
                                "Dataset",
                                "topic-tree",
                            ],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "new-importance-activation-en",
                            "type": "approach_change",
                            "legacy_type": "method_change",
                            "content": (
                                "The memory model's schema defines three distinct metrics: "
                                "importance as a static score at creation, relevance for "
                                "retrieval similarity, and recency or activation as a dynamic "
                                "time-decaying score."
                            ),
                            "importance": 0.89,
                            "evidence": (
                                "The importance score is intentionally static to serve as "
                                "a historical record, while decay is handled separately by "
                                "the recency or activation score."
                            ),
                            "related_topics": ["memory management", "importance score"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 0)
        self.assertEqual(report["matches"][0]["candidate_obj_id"], "new-importance-activation-en")

    def test_semantic_anchors_do_not_treat_memory_as_memo(self) -> None:
        tree = {
            "meetings": [
                {
                    "meeting_id": "0318",
                    "memory_objects": [
                        {
                            "obj_id": "memory-system",
                            "type": "open_issue",
                            "content": (
                                "A memory-system design issue remains open: agents need "
                                "global context when processing long conversations."
                            ),
                            "importance": 0.72,
                            "evidence": (
                                "The discussion was about memory system design and shared "
                                "context, not a paper-comparison benchmark."
                            ),
                            "related_topics": ["memory system design"],
                        }
                    ],
                }
            ]
        }

        obj = iter_l1_objects(tree)[0]

        self.assertNotIn("memo_rag_evaluation", obj["_semantic_anchors"])

    def test_compare_l1_runs_accepts_candidate_with_semantic_anchor_superset(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0318",
                    "memory_objects": [
                        {
                            "obj_id": "old-memo-tradeoff",
                            "type": "decision",
                            "content": (
                                "The MEMO system mainly reduces token consumption and "
                                "latency, but it does not outperform RAG on multi-hop "
                                "questions."
                            ),
                            "importance": 0.80,
                            "evidence": (
                                "MEMO uses fewer tokens and has lower latency, but does "
                                "not beat RAG on multi-hop questions."
                            ),
                            "related_topics": ["MEMO", "RAG", "evaluation"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0318",
                    "memory_objects": [
                        {
                            "obj_id": "new-memory-unrelated",
                            "type": "open_issue",
                            "legacy_type": "open_question",
                            "content": (
                                "The memory system still needs a shared context design "
                                "for sequential agents."
                            ),
                            "importance": 0.62,
                            "evidence": (
                                "Agents need global memory context when processing "
                                "conversation chunks."
                            ),
                            "related_topics": ["memory system design"],
                        },
                        {
                            "obj_id": "new-memo-tradeoff",
                            "type": "argument",
                            "legacy_type": "argument",
                            "content": (
                                "The MEMO evaluation shows a trade-off: lower token use "
                                "and latency, while RAG remains stronger on multi-hop "
                                "questions. The same section also mentions dataset and "
                                "retrieval settings."
                            ),
                            "importance": 0.74,
                            "evidence": (
                                "MEMO low token use and latency; RAG still performs "
                                "better on multi-hop questions in the evaluation dataset."
                            ),
                            "related_topics": ["MEMO", "RAG", "dataset", "retrieval"],
                        },
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 0)
        self.assertEqual(report["matches"][0]["candidate_obj_id"], "new-memo-tradeoff")

    def test_compare_l1_runs_rejects_broad_anchor_only_match(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "old-batch-definition",
                            "type": "open_question",
                            "content": (
                                "The definition of batch remains unresolved: is it only "
                                "a repaired segment, or a higher-level container combining "
                                "related segments and idea units?"
                            ),
                            "importance": 0.72,
                            "evidence": (
                                "Batch may contain related segments and idea units. The "
                                "discussion asks whether this is just repair or a new data "
                                "structure level in the memory representation."
                            ),
                            "related_topics": ["data_structure", "memory representation"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "new-logging-quality",
                            "type": "action_item",
                            "legacy_type": "method_change",
                            "content": (
                                "The development workflow logs each agent prompt and "
                                "result so the UI can inspect idea unit extraction quality."
                            ),
                            "importance": 0.64,
                            "evidence": (
                                "Batch may contain related segments and idea units. The "
                                "discussion asks whether this is just repair or a new data "
                                "structure level in the memory representation. Prompt and "
                                "result logs are saved for every agent call. The UI checks "
                                "idea units for quality after transcript cleanup."
                            ),
                            "related_topics": ["data quality", "development process"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 1)
        self.assertEqual(report["manual_review_queue"][0]["baseline_obj_id"], "old-batch-definition")

    def test_compare_l1_runs_puts_low_importance_watchlist_misses_in_manual_queue(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0318",
                    "memory_objects": [
                        {
                            "obj_id": "old-locomo-definition",
                            "type": "open_question",
                            "content": (
                                "LOCOMO multi-hop evaluation needs a clearer definition "
                                "before the team can compare MEMO and RAG results."
                            ),
                            "importance": 0.61,
                            "evidence": (
                                "The discussion asks what LOCOMO multi-hop means and "
                                "whether the judge evaluates it consistently."
                            ),
                            "related_topics": ["LOCOMO", "multi-hop", "evaluation"],
                        }
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0318",
                    "memory_objects": [
                        {
                            "obj_id": "new-unrelated",
                            "type": "finding",
                            "legacy_type": "result",
                            "content": "The topic-tree view writes append-only update files.",
                            "importance": 0.72,
                            "evidence": "Topic updates are append-only.",
                            "related_topics": ["topic-tree"],
                        }
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)

        self.assertEqual(report["summary"]["high_importance_unmatched_count"], 0)
        self.assertEqual(report["summary"]["watchlist_unmatched_count"], 1)
        self.assertEqual(report["manual_review_queue"][0]["reason"], "watchlist_baseline_unmatched")
        self.assertEqual(report["manual_review_queue"][0]["watchlist_code"], "locomo_multi_hop_definition")

    def test_compare_l1_runs_reports_importance_drift_summary(self) -> None:
        baseline = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "old-1",
                            "type": "decision",
                            "content": "Adopt share_mem as the canonical L1 store.",
                            "importance": 0.82,
                            "evidence": "Adopt share_mem as the canonical L1 store.",
                            "related_topics": ["share_mem"],
                        },
                        {
                            "obj_id": "old-2",
                            "type": "argument",
                            "content": "Keep raw L1 evidence immutable during updates.",
                            "importance": 0.64,
                            "evidence": "Raw L1 evidence must stay immutable.",
                            "related_topics": ["L1 evidence"],
                        },
                    ],
                }
            ]
        }
        candidate = {
            "meetings": [
                {
                    "meeting_id": "0506",
                    "memory_objects": [
                        {
                            "obj_id": "new-1",
                            "type": "decision",
                            "legacy_type": "decision",
                            "content": "Adopt share_mem as the canonical L1 store.",
                            "importance": 0.80,
                            "evidence": "Adopt share_mem as the canonical L1 store.",
                            "related_topics": ["share_mem"],
                        },
                        {
                            "obj_id": "new-2",
                            "type": "argument",
                            "legacy_type": "argument",
                            "content": "Keep raw L1 evidence immutable during updates.",
                            "importance": 0.70,
                            "evidence": "Raw L1 evidence must stay immutable.",
                            "related_topics": ["L1 evidence"],
                        },
                    ],
                }
            ]
        }

        report = compare_l1_trees(baseline, candidate, high_importance_threshold=0.7)
        drift = report["summary"]["importance_delta"]

        self.assertEqual(drift["matched_count"], 2)
        self.assertAlmostEqual(drift["mean_abs"], 0.04, places=4)
        self.assertAlmostEqual(drift["p90_abs"], 0.06, places=4)

    def test_write_comparison_outputs_writes_json_markdown_and_review_queue(self) -> None:
        report = {
            "summary": {
                "baseline_object_count": 1,
                "candidate_object_count": 1,
                "high_importance_unmatched_count": 0,
                "watchlist_unmatched_count": 0,
                "importance_delta": {"matched_count": 0},
            },
            "type_distribution": {
                "baseline": {"todo": 1},
                "candidate": {"action_item": 1},
            },
            "meeting_summaries": [],
            "manual_review_queue": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "comparison"

            write_comparison_outputs(report, out_dir)

            self.assertTrue((out_dir / "comparison_report.json").exists())
            self.assertTrue((out_dir / "comparison_report.md").exists())
            self.assertTrue((out_dir / "manual_review_queue.json").exists())


if __name__ == "__main__":
    unittest.main()
