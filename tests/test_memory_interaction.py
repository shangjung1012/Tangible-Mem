from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
sys.path.insert(0, str(LONG_TERM_DIR))

import recall  # noqa: E402
from embedder import EmbedCache  # noqa: E402
from l1_quality import l1_quality_hashes  # noqa: E402
from memory_activity import (  # noqa: E402
    build_memory_activity_update,
    load_memory_activity_index,
    memory_activity_default_path,
    merge_memory_activity_index,
)
from memory_relations import (  # noqa: E402
    build_cross_meeting_relations,
    format_memory_relations_tag,
    load_memory_relations_index,
    memory_relations_default_path,
    merge_memory_relations_index,
)
from prior_context import build_prior_context_pack, format_prior_context_for_prompt  # noqa: E402


def _obj(
    obj_id: str,
    obj_type: str,
    content: str,
    *,
    importance: float = 0.7,
    evidence: str = "evidence",
    topics: list[str] | None = None,
) -> dict:
    return {
        "obj_id": obj_id,
        "type": obj_type,
        "content": content,
        "importance": importance,
        "evidence": evidence,
        "related_topics": topics or ["memory"],
        "related_obj_ids": [],
    }


class MemoryInteractionTests(unittest.TestCase):
    def test_prior_context_skips_weak_and_stale_quality(self) -> None:
        weak = _obj(
            "L1-0307-001",
            "method_change",
            "Use old weak transcript chunking.",
            topics=["chunking"],
        )
        stale = _obj(
            "L1-0307-002",
            "decision",
            "Old stale decision about memory.",
            topics=["memory"],
        )
        strong = _obj(
            "L1-0408-001",
            "method_change",
            "Use multi-agent L1 extraction for memory.",
            topics=["multi-agent", "memory"],
        )
        tree = {
            "project_profile": {},
            "meetings": [
                {
                    "meeting_id": "0307",
                    "meeting_date": "2026-03-07",
                    "memory_objects": [weak, stale],
                },
                {
                    "meeting_id": "0408",
                    "meeting_date": "2026-04-08",
                    "memory_objects": [strong],
                },
            ],
        }
        old_stale = {**stale, "content": "Different old content"}
        quality_index = {
            weak["obj_id"]: {"quality_level": "weak", **l1_quality_hashes(weak)},
            stale["obj_id"]: {"quality_level": "strong", **l1_quality_hashes(old_stale)},
            strong["obj_id"]: {"quality_level": "strong", **l1_quality_hashes(strong)},
        }

        pack = build_prior_context_pack(
            tree=tree,
            meeting_id="0422",
            transcript="We discuss multi-agent memory extraction and chunking.",
            quality_index=quality_index,
        )
        prompt_text = format_prior_context_for_prompt(pack)
        obj_ids = {item["obj_id"] for item in pack["items"]}

        self.assertIn(strong["obj_id"], obj_ids)
        self.assertNotIn(weak["obj_id"], obj_ids)
        self.assertNotIn(stale["obj_id"], obj_ids)
        self.assertIn("never evidence", prompt_text)
        self.assertIn("current transcript", prompt_text)

    def test_cross_meeting_linker_builds_conservative_relations(self) -> None:
        old_question = _obj(
            "L1-0307-001",
            "open_question",
            "How should memory decay keep important old events retrievable?",
            topics=["memory decay", "recall"],
        )
        old_method = _obj(
            "L1-0307-002",
            "method_change",
            "Use full transcript bridge for L1 extraction.",
            topics=["bridge", "l1 extraction"],
        )
        new_result = _obj(
            "L1-0422-001",
            "result",
            "The memory decay question is resolved by using activation sidecars.",
            topics=["memory decay", "recall"],
        )
        new_method = _obj(
            "L1-0422-002",
            "method_change",
            "改用 multi-agent L1 extraction 取代 full transcript bridge.",
            topics=["bridge", "l1 extraction"],
        )
        tree = {
            "meetings": [
                {"meeting_id": "0307", "memory_objects": [old_question, old_method]},
                {"meeting_id": "0422", "memory_objects": [new_result, new_method]},
            ]
        }

        relations = build_cross_meeting_relations(
            tree=tree,
            source_meeting={"meeting_id": "0422", "memory_objects": [new_result, new_method]},
        )

        result_relations = relations[new_result["obj_id"]]
        method_relations = relations[new_method["obj_id"]]
        self.assertTrue(any(r["relation"] == "resolves" for r in result_relations))
        self.assertTrue(any(r["relation"] == "supersedes" for r in method_relations))
        self.assertIn("source_content_hash", result_relations[0])
        self.assertIn("target_content_hash", result_relations[0])
        self.assertTrue(all(float(r["confidence"]) >= 0.58 for r in result_relations + method_relations))

    def test_cross_meeting_linker_uses_viewpoint_keys_before_loose_matching(self) -> None:
        old_result = _obj(
            "L1-0325-001",
            "result",
            "Unimportant old memories should fade by importance and relevance while important events stay retrievable.",
            topics=["long-term memory"],
        )
        new_method = _obj(
            "L1-0422-001",
            "method_change",
            "長期記憶需要依重要性與相關性做衰減權重，避免過期事項干擾 recall。",
            topics=["activation"],
        )
        tree = {
            "meetings": [
                {"meeting_id": "0325", "memory_objects": [old_result]},
                {"meeting_id": "0422", "memory_objects": [new_method]},
            ]
        }

        relations = build_cross_meeting_relations(
            tree=tree,
            source_meeting={"meeting_id": "0422", "memory_objects": [new_method]},
        )

        relation = relations[new_method["obj_id"]][0]
        self.assertEqual(relation["relation"], "reactivates")
        self.assertIn("long_term_forgetting_decay", relation["shared_viewpoint_keys"])

    def test_stale_relation_metadata_is_hidden_from_prompt_tags(self) -> None:
        source = _obj("L1-0422-001", "method_change", "New source content")
        target = _obj("L1-0307-001", "method_change", "Target content")
        stale_source = {**source, "content": "Old source content"}
        relations_index = {
            source["obj_id"]: [
                {
                    "target_obj_id": target["obj_id"],
                    "relation": "continues",
                    **l1_quality_hashes(stale_source),
                    "source_content_hash": l1_quality_hashes(stale_source)["content_hash"],
                    "source_evidence_hash": l1_quality_hashes(stale_source)["evidence_hash"],
                    "target_content_hash": l1_quality_hashes(target)["content_hash"],
                    "target_evidence_hash": l1_quality_hashes(target)["evidence_hash"],
                }
            ]
        }

        self.assertEqual(format_memory_relations_tag(source, relations_index), "relations=none")

    def test_relation_index_merge_and_activity_reactivation(self) -> None:
        old_todo = _obj(
            "L1-0307-001",
            "todo",
            "Follow up on memory activation scoring.",
            topics=["activity"],
            importance=0.55,
        )
        new_decision = _obj(
            "L1-0422-001",
            "decision",
            "Continue memory activation scoring work.",
            topics=["activity"],
        )
        tree = {
            "meetings": [
                {
                    "meeting_id": "0307",
                    "meeting_date": "2026-03-07",
                    "memory_objects": [old_todo],
                },
                {
                    "meeting_id": "0422",
                    "meeting_date": "2026-04-22",
                    "memory_objects": [new_decision],
                },
            ]
        }
        relation_updates = {
            new_decision["obj_id"]: [
                {
                    "target_obj_id": old_todo["obj_id"],
                    "relation": "reactivates",
                    "confidence": 0.8,
                    "source_meeting_id": "0422",
                    "target_meeting_id": "0307",
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            tree_path = Path(tmp) / "tree.json"
            relations_path = memory_relations_default_path(tree_path)
            activity_path = memory_activity_default_path(tree_path)
            merge_memory_relations_index(relations_path, relation_updates)
            activity = build_memory_activity_update(
                tree=tree,
                meeting_id="0422",
                relation_updates=relation_updates,
                now=datetime(2026, 5, 6, tzinfo=timezone.utc),
            )
            merge_memory_activity_index(activity_path, activity)

            loaded_relations = load_memory_relations_index(relations_path)
            loaded_activity = load_memory_activity_index(activity_path)

        self.assertEqual(loaded_relations, relation_updates)
        self.assertEqual(loaded_activity[old_todo["obj_id"]]["state"], "reactivated")
        self.assertGreaterEqual(loaded_activity[old_todo["obj_id"]]["activation"], 0.82)
        self.assertEqual(loaded_activity[new_decision["obj_id"]]["state"], "active")

    def test_activity_decay_protects_durable_research_context_not_logistics(self) -> None:
        durable = _obj(
            "L1-0307-001",
            "todo",
            "Design the memory retrieval process that lets the agent use long-term memory during real-time responses.",
            importance=0.78,
            topics=["memory retrieval", "agent architecture"],
        )
        logistical = _obj(
            "L1-0307-002",
            "todo",
            "Create a lab Google account for API key billing.",
            importance=0.82,
            topics=["API key management", "project budget"],
        )
        tree = {
            "meetings": [
                {
                    "meeting_id": "0307",
                    "meeting_date": "2026-03-07",
                    "memory_objects": [durable, logistical],
                }
            ]
        }

        activity = build_memory_activity_update(
            tree=tree,
            meeting_id="0422",
            relation_updates={},
            now=datetime(2026, 5, 6, tzinfo=timezone.utc),
        )

        self.assertEqual(activity[durable["obj_id"]]["state"], "fading")
        self.assertGreaterEqual(activity[durable["obj_id"]]["activation"], 0.46)
        self.assertTrue(activity[durable["obj_id"]]["durable_context"])
        self.assertEqual(activity[logistical["obj_id"]]["state"], "dormant")
        self.assertEqual(activity[logistical["obj_id"]]["activation"], 0.15)
        self.assertFalse(activity[logistical["obj_id"]]["durable_context"])

    def test_activity_decay_protects_segmentation_and_function_calling_context(self) -> None:
        function_calling = _obj(
            "L1-0422-001",
            "todo",
            "Function Calling lets Gemini dynamically adjust start_line and end_line while reading transcript spans.",
            importance=0.70,
            topics=["Function Calling", "Segmentation", "Architectural design"],
        )
        idea_units = _obj(
            "L1-0422-002",
            "todo",
            "Use information entropy to identify idea unit boundaries for dynamic segmentation.",
            importance=0.66,
            topics=["Idea Units", "Dynamic Segmentation"],
        )
        tree = {
            "meetings": [
                {
                    "meeting_id": "0422",
                    "meeting_date": "2026-04-22",
                    "memory_objects": [function_calling, idea_units],
                }
            ]
        }

        activity = build_memory_activity_update(
            tree=tree,
            meeting_id="SIM05",
            relation_updates={},
            now=datetime(2026, 5, 27, tzinfo=timezone.utc),
        )

        self.assertEqual(activity[function_calling["obj_id"]]["state"], "fading")
        self.assertTrue(activity[function_calling["obj_id"]]["durable_context"])
        self.assertEqual(activity[idea_units["obj_id"]]["state"], "fading")
        self.assertTrue(activity[idea_units["obj_id"]]["durable_context"])

    def test_low_confidence_relation_does_not_reactivate_old_activity(self) -> None:
        old_todo = _obj(
            "L1-0307-001",
            "todo",
            "Review project logistics.",
            importance=0.55,
            topics=["memory"],
        )
        new_result = _obj(
            "L1-0422-001",
            "result",
            "The memory architecture discussion continued.",
            topics=["memory"],
        )
        tree = {
            "meetings": [
                {
                    "meeting_id": "0307",
                    "meeting_date": "2026-03-07",
                    "memory_objects": [old_todo],
                },
                {
                    "meeting_id": "0422",
                    "meeting_date": "2026-04-22",
                    "memory_objects": [new_result],
                },
            ]
        }

        activity = build_memory_activity_update(
            tree=tree,
            meeting_id="0422",
            relation_updates={
                new_result["obj_id"]: [
                    {
                        "target_obj_id": old_todo["obj_id"],
                        "relation": "reactivates",
                        "confidence": 0.64,
                        "source_meeting_id": "0422",
                        "target_meeting_id": "0307",
                    }
                ]
            },
            now=datetime(2026, 5, 6, tzinfo=timezone.utc),
        )

        self.assertEqual(activity[old_todo["obj_id"]]["state"], "dormant")
        self.assertEqual(activity[old_todo["obj_id"]]["activation"], 0.15)
        self.assertEqual(activity[old_todo["obj_id"]]["touch_count"], 0)

    def test_cross_meeting_linker_does_not_reactivate_from_broad_topic_only(self) -> None:
        old_todo = _obj(
            "L1-0307-001",
            "todo",
            "Create a shared blackboard for agents.",
            topics=["memory"],
        )
        new_result = _obj(
            "L1-0422-001",
            "result",
            "The interface should display final candidate counts.",
            topics=["memory"],
        )
        tree = {
            "meetings": [
                {"meeting_id": "0307", "memory_objects": [old_todo]},
                {"meeting_id": "0422", "memory_objects": [new_result]},
            ]
        }

        relations = build_cross_meeting_relations(
            tree=tree,
            source_meeting={"meeting_id": "0422", "memory_objects": [new_result]},
        )

        self.assertNotIn(new_result["obj_id"], relations)

    def test_recall_activity_soft_penalty_does_not_filter_high_semantic_match(self) -> None:
        dormant = _obj(
            "L1-0307-001",
            "todo",
            "Follow up on activation scoring.",
            topics=["activation"],
            importance=0.55,
        )
        tree = {
            "meetings": [
                {
                    "meeting_id": "0307",
                    "meeting_date": "2026-03-07",
                    "timestamp": "2026-03-07T00:00:00Z",
                    "phase_id": "",
                    "memory_objects": [dormant],
                }
            ]
        }
        activity_index = {
            dormant["obj_id"]: {
                "activation": 0.2,
                "state": "dormant",
                **l1_quality_hashes(dormant),
            }
        }

        with patch("recall.embed_text", return_value=[1.0, 0.0]):
            results = recall.search_l1_semantic(
                tree=tree,
                query_emb=[1.0, 0.0],
                api_key=[],
                cache=EmbedCache(path=Path(tempfile.gettempdir()) / "unused-cache.json"),
                query_date=datetime(2026, 5, 6, tzinfo=timezone.utc),
                top_k=5,
                activity_index=activity_index,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["activity_state"], "dormant")
        self.assertEqual(results[0]["s_activation"], 0.2)
        self.assertGreater(results[0]["score"], 0.0)

    def test_recall_relation_graph_expands_current_linked_l1_without_hard_filtering(self) -> None:
        source = _obj("L1-0422-001", "method_change", "Adopt activation sidecar.")
        target = _obj("L1-0307-001", "open_question", "How should activation decay work?")
        source_hashes = l1_quality_hashes(source)
        target_hashes = l1_quality_hashes(target)
        tree = {
            "meetings": [
                {
                    "meeting_id": "0307",
                    "meeting_date": "2026-03-07",
                    "timestamp": "2026-03-07T00:00:00Z",
                    "phase_id": "",
                    "memory_objects": [target],
                },
                {
                    "meeting_id": "0422",
                    "meeting_date": "2026-04-22",
                    "timestamp": "2026-04-22T00:00:00Z",
                    "phase_id": "",
                    "memory_objects": [source],
                },
            ]
        }
        primary = [{"obj_id": source["obj_id"], "score": 0.9}]
        relations_index = {
            source["obj_id"]: [
                {
                    "target_obj_id": target["obj_id"],
                    "relation": "reactivates",
                    "confidence": 0.8,
                    "source_content_hash": source_hashes["content_hash"],
                    "source_evidence_hash": source_hashes["evidence_hash"],
                    "target_content_hash": target_hashes["content_hash"],
                    "target_evidence_hash": target_hashes["evidence_hash"],
                }
            ]
        }

        expanded = recall.expand_relation_graph(tree, primary, relations_index)

        self.assertEqual({item["obj_id"] for item in expanded}, {source["obj_id"], target["obj_id"]})
        linked = next(item for item in expanded if item["obj_id"] == target["obj_id"])
        self.assertEqual(linked["source"], "long_term_l1_linked")
        self.assertEqual(linked["linked_from_obj_id"], source["obj_id"])


if __name__ == "__main__":
    unittest.main()
