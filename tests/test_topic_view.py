from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from share_mem.topic_view import (  # noqa: E402
    TopicViewHashMismatchError,
    _concept_keys_for_obj,
    build_topic_view_outputs,
    load_topic_index,
    load_topic_tree,
)
from share_mem.store import refresh_share_mem_outputs  # noqa: E402
from share_mem.validate_topic_view import validate_topic_view_outputs  # noqa: E402


def _obj(
    obj_id: str,
    obj_type: str,
    content: str,
    *,
    topics: list[str],
    evidence: str = "evidence",
    related_obj_ids: list[str] | None = None,
) -> dict:
    return {
        "obj_id": obj_id,
        "type": obj_type,
        "content": content,
        "importance": 0.75,
        "evidence": evidence,
        "related_topics": topics,
        "related_obj_ids": related_obj_ids or [],
    }


def _tree() -> dict:
    return {
        "tree_version": 1,
        "last_updated_utc": "2026-05-08T00:00:00Z",
        "project_profile": {},
        "phases": [],
        "meetings": [
            {
                "meeting_id": "0307",
                "timestamp": "2026-03-07T00:00:00Z",
                "meeting_date": "2026-03-07",
                "source_file": "meeting_recording/transcript/grace/0307.txt",
                "phase_id": "",
                "memory_objects": [
                    _obj(
                        "L1-0307-001",
                        "decision",
                        "Use shared L1 memory as the evidence base.",
                        topics=["shared-l1", "memory"],
                    ),
                    _obj(
                        "L1-0307-002",
                        "todo",
                        "Prepare the poster demo flow.",
                        topics=["poster-demo"],
                    ),
                ],
            },
            {
                "meeting_id": "0318",
                "timestamp": "2026-03-18T00:00:00Z",
                "meeting_date": "2026-03-18",
                "source_file": "meeting_recording/transcript/grace/0318.txt",
                "phase_id": "",
                "memory_objects": [
                    _obj(
                        "L1-0318-001",
                        "method_change",
                        "Short-term and long-term should both read shared L1 memory.",
                        topics=["shared-l1", "memory"],
                    ),
                ],
            },
            {
                "meeting_id": "0325",
                "timestamp": "2026-03-25T00:00:00Z",
                "meeting_date": "2026-03-25",
                "source_file": "meeting_recording/transcript/grace/0325.txt",
                "phase_id": "",
                "memory_objects": [
                    _obj(
                        "L1-0325-001",
                        "open_question",
                        "How should the topic-tree view append updates without changing old L1?",
                        topics=["topic-tree", "memory"],
                    ),
                ],
            },
        ],
    }


def _topic_assignment_tree() -> dict:
    return {
        "tree_version": 1,
        "last_updated_utc": "2026-05-08T00:00:00Z",
        "project_profile": {},
        "phases": [],
        "meetings": [
            {
                "meeting_id": "0429",
                "timestamp": "2026-04-29T00:00:00Z",
                "meeting_date": "2026-04-29",
                "source_file": "meeting_recording/transcript/grace/0429.txt",
                "phase_id": "",
                "memory_objects": [
                    _obj(
                        "L1-0429-025",
                        "argument",
                        (
                            "The memory system differs from RAG by using hierarchical "
                            "memory processing with L1 issues, L2 objects, and repeated "
                            "mentions to update importance."
                        ),
                        topics=["memory", "memory architecture"],
                        evidence="hierarchical memory processing is different from RAG",
                    ),
                    _obj(
                        "L1-0429-030",
                        "finding",
                        "Fixed chunk boundaries can fragment a topic across windows.",
                        topics=["data_fragmentation"],
                        evidence="fixed chunk boundaries fragment the discussion",
                    ),
                ],
            },
            {
                "meeting_id": "0506",
                "timestamp": "2026-05-06T00:00:00Z",
                "meeting_date": "2026-05-06",
                "source_file": "meeting_recording/transcript/grace/0506.txt",
                "phase_id": "",
                "memory_objects": [
                    _obj(
                        "L1-0506-009",
                        "argument",
                        (
                            "A top-down processing architecture was debated against "
                            "bottom-up merging for the long-term memory system."
                        ),
                        topics=["memory", "design decision"],
                        evidence="top-down processing architecture versus bottom-up merging",
                    ),
                    _obj(
                        "L1-0506-010",
                        "open_question",
                        "Segment repair is needed when data fragmentation crosses chunks.",
                        topics=["data fragmentation"],
                        evidence="data fragmentation across chunks requires repair",
                    ),
                ],
            },
        ],
    }


class TopicViewTests(unittest.TestCase):
    def test_build_topic_view_writes_meeting_updates_tree_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"

            manifest = build_topic_view_outputs(root=root, tree=_tree(), mode="hybrid")

            self.assertEqual(manifest["meeting_count"], 3)
            self.assertEqual(manifest["topic_event_count"], 4)
            self.assertEqual(manifest["topic_count"], 3)
            self.assertTrue((root / "topic_updates" / "0307.json").exists())
            self.assertTrue((root / "topic_updates" / "0318.json").exists())
            self.assertTrue((root / "topic_updates" / "0325.json").exists())
            self.assertTrue((root / "topic_tree.json").exists())
            self.assertTrue((root / "topic_index.json").exists())

            topic_tree = load_topic_tree(root)
            topic_index = load_topic_index(root)

            self.assertEqual(topic_tree["schema_version"], 1)
            self.assertEqual(topic_index["L1-0307-001"]["meeting_id"], "0307")
            self.assertEqual(
                topic_index["L1-0318-001"]["topic_id"],
                topic_index["L1-0307-001"]["topic_id"],
            )
            self.assertNotEqual(
                topic_index["L1-0325-001"]["topic_id"],
                topic_index["L1-0307-001"]["topic_id"],
            )
            self.assertEqual(topic_index["L1-0325-001"]["topic_path"], ["memory", "topic-tree"])

            update_0307 = json.loads(
                (root / "topic_updates" / "0307.json").read_text(encoding="utf-8")
            )
            update_0318 = json.loads(
                (root / "topic_updates" / "0318.json").read_text(encoding="utf-8")
            )
            update_0325 = json.loads(
                (root / "topic_updates" / "0325.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [event["action"] for event in update_0307["topic_events"]],
                ["new_l3", "new_l3"],
            )
            self.assertEqual(update_0318["topic_events"][0]["action"], "assign_existing")
            self.assertEqual(update_0325["topic_events"][0]["action"], "new_l2")

    def test_build_topic_view_refreshes_manifest_topic_view_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            refresh_share_mem_outputs(root=root, tree=_tree(), source_transcript_dir=Path(tmp))

            build_topic_view_outputs(root=root, tree=_tree(), mode="hybrid")

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["topic_view"]["exists"])
            self.assertEqual(manifest["topic_view"]["topic_event_count"], 4)

    def test_clean_topic_view_removes_old_topic_research_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            log_path = root / "topic_research_logs" / "old" / "api_calls" / "001.json"
            log_path.parent.mkdir(parents=True)
            log_path.write_text("{}", encoding="utf-8")

            build_topic_view_outputs(
                root=root,
                tree=_tree(),
                mode="hybrid",
                clean_topic_view=True,
            )

            self.assertFalse((root / "topic_research_logs" / "old").exists())

    def test_resume_skips_matching_update_without_rewriting_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            build_topic_view_outputs(root=root, tree=_tree(), mode="hybrid")
            update_path = root / "topic_updates" / "0318.json"
            before = update_path.read_text(encoding="utf-8")

            manifest = build_topic_view_outputs(
                root=root,
                tree=_tree(),
                mode="hybrid",
                resume=True,
            )

            self.assertGreaterEqual(manifest["skipped_meeting_count"], 3)
            self.assertEqual(update_path.read_text(encoding="utf-8"), before)

    def test_hash_mismatch_requires_force_or_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            build_topic_view_outputs(root=root, tree=_tree(), mode="hybrid")
            changed = _tree()
            changed["meetings"][1]["memory_objects"][0]["content"] = (
                "Shared L1 memory should feed both short-term and long-term."
            )

            with self.assertRaises(TopicViewHashMismatchError):
                build_topic_view_outputs(root=root, tree=changed, mode="hybrid")

            manifest = build_topic_view_outputs(
                root=root,
                tree=changed,
                mode="hybrid",
                force_meetings={"0318"},
            )

            self.assertEqual(manifest["meeting_count"], 3)
            topic_index = load_topic_index(root)
            self.assertEqual(topic_index["L1-0318-001"]["meeting_id"], "0318")

    def test_force_rebuild_does_not_use_future_topic_context_for_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            build_topic_view_outputs(root=root, tree=_tree(), mode="hybrid")
            changed = _tree()
            changed["meetings"][1]["memory_objects"][0]["content"] = (
                "Shared L1 memory remains the common base for short-term and long-term."
            )
            candidates_by_obj: dict[str, list[str]] = {}

            def spy_assigner(**kwargs: dict) -> dict:
                candidates_by_obj[kwargs["obj"]["obj_id"]] = [
                    str(candidate["topic_label"]) for candidate in kwargs["candidates"]
                ]
                return {}

            build_topic_view_outputs(
                root=root,
                tree=changed,
                mode="hybrid",
                force_meetings={"0318"},
                llm_assigner=spy_assigner,
            )

            self.assertIn("shared-l1", candidates_by_obj["L1-0318-001"])
            self.assertNotIn("topic-tree", candidates_by_obj["L1-0318-001"])

    def test_llm_assigner_can_choose_from_candidate_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"

            def fake_assigner(**kwargs: dict) -> dict:
                if kwargs["obj"]["obj_id"] != "L1-0325-001":
                    return {}
                shared_l1 = next(
                    candidate
                    for candidate in kwargs["candidates"]
                    if candidate["topic_label"] == "shared-l1"
                )
                return {
                    "action": "assign_existing",
                    "root_topic_id": shared_l1["root_topic_id"],
                    "topic_id": shared_l1["topic_id"],
                    "root_label": shared_l1["root_label"],
                    "topic_label": shared_l1["topic_label"],
                    "state_summary": "LLM selected the shared L1 memory topic.",
                    "rationale": "The object asks about append-only L1 memory updates.",
                }

            build_topic_view_outputs(
                root=root,
                tree=_tree(),
                mode="hybrid",
                llm_assigner=fake_assigner,
            )

            topic_index = load_topic_index(root)
            self.assertEqual(
                topic_index["L1-0325-001"]["topic_id"],
                topic_index["L1-0307-001"]["topic_id"],
            )
            update_0325 = json.loads(
                (root / "topic_updates" / "0325.json").read_text(encoding="utf-8")
            )
            self.assertEqual(update_0325["topic_events"][0]["assignment_method"], "llm")
            topic_tree = load_topic_tree(root)
            memory_root = next(
                root_node
                for root_node in topic_tree["topic_roots"]
                if root_node["label"] == "memory"
            )
            shared_node = next(
                child for child in memory_root["children"] if child["label"] == "shared-l1"
            )
            self.assertEqual(
                shared_node["current_state"],
                "LLM selected the shared L1 memory topic.",
            )

    def test_llm_assign_existing_outside_candidates_falls_back_to_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"

            def fake_assigner(**kwargs: dict) -> dict:
                if kwargs["obj"]["obj_id"] != "L1-0325-001":
                    return {}
                return {
                    "action": "assign_existing",
                    "topic_id": "L2-not-a-candidate",
                    "root_label": "memory",
                    "topic_label": "made-up-topic",
                    "state_summary": "This decision should be ignored.",
                }

            build_topic_view_outputs(
                root=root,
                tree=_tree(),
                mode="hybrid",
                llm_assigner=fake_assigner,
            )

            topic_index = load_topic_index(root)
            self.assertEqual(topic_index["L1-0325-001"]["topic_path"], ["memory", "topic-tree"])
            update_0325 = json.loads(
                (root / "topic_updates" / "0325.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                update_0325["topic_events"][0]["assignment_method"],
                "deterministic",
            )

    def test_llm_cannot_override_memory_processing_concept_with_generic_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            tree = {
                "tree_version": 1,
                "last_updated_utc": "2026-05-08T00:00:00Z",
                "project_profile": {},
                "phases": [],
                "meetings": [
                    {
                        "meeting_id": "0429",
                        "timestamp": "2026-04-29T00:00:00Z",
                        "meeting_date": "2026-04-29",
                        "source_file": "meeting_recording/transcript/grace/0429.txt",
                        "phase_id": "",
                        "memory_objects": [
                            _obj(
                                "L1-0429-001",
                                "finding",
                                "Fixed chunk windows create text splitting problems.",
                                topics=["text splitting", "long context processing"],
                            ),
                            _obj(
                                "L1-0429-002",
                                "argument",
                                (
                                    "The memory system differs from RAG through "
                                    "hierarchical memory processing across L1, L2, and L3."
                                ),
                                topics=["memory", "memory architecture"],
                            ),
                        ],
                    },
                    {
                        "meeting_id": "0506",
                        "timestamp": "2026-05-06T00:00:00Z",
                        "meeting_date": "2026-05-06",
                        "source_file": "meeting_recording/transcript/grace/0506.txt",
                        "phase_id": "",
                        "memory_objects": [
                            _obj(
                                "L1-0506-001",
                                "open_issue",
                                (
                                    "A top-down segment-first processing architecture was "
                                    "debated against bottom-up idea unit merging."
                                ),
                                topics=["text splitting", "long context processing"],
                            )
                        ],
                    },
                ],
            }

            def bad_assigner(**kwargs: dict) -> dict:
                if kwargs["obj"]["obj_id"] != "L1-0506-001":
                    return {}
                generic = next(
                    candidate
                    for candidate in kwargs["candidates"]
                    if candidate["topic_label"] == "long context processing"
                    or candidate["topic_label"] == "text splitting"
                )
                return {
                    "action": "assign_existing",
                    "root_topic_id": generic["root_topic_id"],
                    "topic_id": generic["topic_id"],
                    "root_label": generic["root_label"],
                    "topic_label": generic["topic_label"],
                    "state_summary": "This generic assignment should be rejected.",
                    "rationale": "bad override",
                }

            build_topic_view_outputs(
                root=root,
                tree=tree,
                mode="hybrid",
                llm_assigner=bad_assigner,
            )

            topic_index = load_topic_index(root)
            self.assertEqual(
                topic_index["L1-0506-001"]["topic_path"],
                ["memory", "memory processing architecture"],
            )

    def test_protected_data_fragmentation_concept_opens_topic_before_lexical_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            tree = {
                "tree_version": 1,
                "last_updated_utc": "2026-05-08T00:00:00Z",
                "project_profile": {},
                "phases": [],
                "meetings": [
                    {
                        "meeting_id": "0429",
                        "timestamp": "2026-04-29T00:00:00Z",
                        "meeting_date": "2026-04-29",
                        "source_file": "meeting_recording/transcript/grace/0429.txt",
                        "phase_id": "",
                        "memory_objects": [
                            _obj(
                                "L1-0429-001",
                                "open_issue",
                                (
                                    "Long context processing uses a candidate memory "
                                    "integration mechanism for transcript chunks."
                                ),
                                topics=["long context processing", "candidate memory integration"],
                            ),
                            _obj(
                                "L1-0429-002",
                                "decision",
                                (
                                    "To handle topics that span across processing chunks, "
                                    "the system stores a candidate object and merges "
                                    "subsequent relevant content to prevent information "
                                    "loss at chunk boundaries."
                                ),
                                topics=["long context processing", "text splitting"],
                            ),
                        ],
                    }
                ],
            }

            build_topic_view_outputs(root=root, tree=tree, mode="hybrid")

            topic_index = load_topic_index(root)
            self.assertEqual(
                topic_index["L1-0429-002"]["topic_path"],
                ["data fragmentation", "data fragmentation"],
            )

    def test_data_fragmentation_topic_keeps_dedicated_root_even_with_memory_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            tree = {
                "tree_version": 1,
                "last_updated_utc": "2026-05-08T00:00:00Z",
                "project_profile": {},
                "phases": [],
                "meetings": [
                    {
                        "meeting_id": "0506",
                        "timestamp": "2026-05-06T00:00:00Z",
                        "meeting_date": "2026-05-06",
                        "source_file": "meeting_recording/transcript/grace/0506.txt",
                        "phase_id": "",
                        "memory_objects": [
                            _obj(
                                "L1-0506-001",
                                "open_issue",
                                (
                                    "The memory system has data fragmentation when "
                                    "idea unit extraction misses transcript lines."
                                ),
                                topics=["memory system implementation", "output quality"],
                            )
                        ],
                    }
                ],
            }

            build_topic_view_outputs(root=root, tree=tree, mode="hybrid")

            topic_index = load_topic_index(root)
            self.assertEqual(
                topic_index["L1-0506-001"]["topic_path"],
                ["data fragmentation", "data fragmentation"],
            )

    def test_memo_rag_evaluation_is_not_memory_processing_architecture(self) -> None:
        obj = _obj(
            "L1-0318-001",
            "finding",
            (
                "The MEM 0 evaluation compared token consumption, latency, "
                "RAG baseline behavior, and multi-hop correctness."
            ),
            topics=["memory system performance", "model configuration"],
        )

        concepts = _concept_keys_for_obj(obj)

        self.assertIn("memory evaluation strategy", concepts)
        self.assertNotIn("memory processing architecture", concepts)

    def test_locomo_question_taxonomy_routes_to_memory_evaluation_not_dataset_sourcing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            tree = {
                "tree_version": 1,
                "last_updated_utc": "2026-05-08T00:00:00Z",
                "project_profile": {},
                "phases": [],
                "meetings": [
                    {
                        "meeting_id": "0318",
                        "timestamp": "2026-03-18T00:00:00Z",
                        "meeting_date": "2026-03-18",
                        "source_file": "meeting_recording/transcript/grace/0318.txt",
                        "phase_id": "",
                        "memory_objects": [
                            _obj(
                                "L1-0318-001",
                                "argument",
                                (
                                    "In the LOCOMO dataset, a multi-hop question is "
                                    "defined by the number of reasoning sub-problems "
                                    "rather than conversational turns."
                                ),
                                topics=["dataset", "question taxonomy"],
                            )
                        ],
                    }
                ],
            }

            build_topic_view_outputs(root=root, tree=tree, mode="hybrid")

            topic_index = load_topic_index(root)
            self.assertEqual(
                topic_index["L1-0318-001"]["topic_path"],
                ["memory", "memory evaluation strategy"],
            )

    def test_memory_source_anchor_objects_do_not_merge_into_processing_architecture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            tree = {
                "tree_version": 1,
                "last_updated_utc": "2026-05-08T00:00:00Z",
                "project_profile": {},
                "phases": [],
                "meetings": [
                    {
                        "meeting_id": "0325",
                        "timestamp": "2026-03-25T00:00:00Z",
                        "meeting_date": "2026-03-25",
                        "source_file": "meeting_recording/transcript/grace/0325.txt",
                        "phase_id": "",
                        "memory_objects": [
                            _obj(
                                "L1-0325-001",
                                "finding",
                                (
                                    "Memory objects should link back to specific audio "
                                    "timestamps in the original recording so the agent can "
                                    "play the source evidence."
                                ),
                                topics=["memory system architecture", "source link"],
                            )
                        ],
                    }
                ],
            }

            build_topic_view_outputs(root=root, tree=tree, mode="hybrid")

            topic_index = load_topic_index(root)
            self.assertEqual(
                topic_index["L1-0325-001"]["topic_path"],
                ["memory", "memory evidence anchoring"],
            )

    def test_protected_data_fragmentation_ignores_unrelated_relation_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            tree = {
                "tree_version": 1,
                "last_updated_utc": "2026-05-08T00:00:00Z",
                "project_profile": {},
                "phases": [],
                "meetings": [
                    {
                        "meeting_id": "0506",
                        "timestamp": "2026-05-06T00:00:00Z",
                        "meeting_date": "2026-05-06",
                        "source_file": "meeting_recording/transcript/grace/0506.txt",
                        "phase_id": "",
                        "memory_objects": [
                            _obj(
                                "L1-0506-001",
                                "argument",
                                (
                                    "Agent-based long-text processing has semantic "
                                    "issues in text chunking."
                                ),
                                topics=[
                                    "agent-based long-text processing",
                                    "semantic issues in text chunking",
                                ],
                            ),
                            _obj(
                                "L1-0506-002",
                                "open_issue",
                                (
                                    "The batch definition is unclear: it may be a repair "
                                    "mechanism for broken segments, a grouping of chunks, "
                                    "or a merger of idea units, creating data fragmentation."
                                ),
                                topics=["text chunking", "semantic integrity"],
                                related_obj_ids=["L1-0506-001"],
                            ),
                        ],
                    }
                ],
            }

            build_topic_view_outputs(root=root, tree=tree, mode="hybrid")

            topic_index = load_topic_index(root)
            self.assertEqual(
                topic_index["L1-0506-002"]["topic_path"],
                ["data fragmentation", "data fragmentation"],
            )

    def test_memory_lifecycle_concept_is_not_absorbed_by_llm_into_processing_architecture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            tree = {
                "tree_version": 1,
                "last_updated_utc": "2026-05-08T00:00:00Z",
                "project_profile": {},
                "phases": [],
                "meetings": [
                    {
                        "meeting_id": "0506",
                        "timestamp": "2026-05-06T00:00:00Z",
                        "meeting_date": "2026-05-06",
                        "source_file": "meeting_recording/transcript/grace/0506.txt",
                        "phase_id": "",
                        "memory_objects": [
                            _obj(
                                "L1-0506-001",
                                "decision",
                                (
                                    "The memory hierarchy uses L1, L2, and L3 parent "
                                    "objects during retrieval."
                                ),
                                topics=["memory system architecture"],
                            ),
                            _obj(
                                "L1-0506-002",
                                "open_issue",
                                (
                                    "There is uncertainty about how the importance score "
                                    "is used and what discard as L1 means."
                                ),
                                topics=["importance score", "memory management"],
                            ),
                        ],
                    }
                ],
            }

            def bad_assigner(**kwargs):
                obj = kwargs["obj"]
                candidates = kwargs["candidates"]
                if obj["obj_id"] == "L1-0506-002":
                    processing = next(
                        candidate
                        for candidate in candidates
                        if candidate["topic_label"] == "memory processing architecture"
                    )
                    return {
                        "action": "assign_existing",
                        "topic_id": processing["topic_id"],
                        "state_summary": "incorrectly merged",
                        "rationale": "bad merge",
                    }
                return None

            build_topic_view_outputs(
                root=root,
                tree=tree,
                mode="hybrid",
                llm_assigner=bad_assigner,
            )

            topic_index = load_topic_index(root)
            self.assertEqual(
                topic_index["L1-0506-002"]["topic_path"],
                ["memory", "memory lifecycle"],
            )

    def test_related_obj_ids_assign_generic_update_to_prior_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            tree = _tree()
            tree["meetings"][2]["memory_objects"][0] = _obj(
                "L1-0325-001",
                "open_question",
                "How should new updates stay connected to the earlier shared evidence base?",
                topics=["memory"],
                related_obj_ids=["L1-0307-001"],
            )

            build_topic_view_outputs(root=root, tree=tree, mode="hybrid")

            topic_index = load_topic_index(root)
            self.assertEqual(
                topic_index["L1-0325-001"]["topic_id"],
                topic_index["L1-0307-001"]["topic_id"],
            )
            update_0325 = json.loads(
                (root / "topic_updates" / "0325.json").read_text(encoding="utf-8")
            )
            self.assertEqual(update_0325["topic_events"][0]["action"], "assign_existing")

    def test_relation_sidecar_assigns_generic_update_to_prior_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            tree = _tree()
            tree["meetings"][2]["memory_objects"][0] = _obj(
                "L1-0325-001",
                "open_question",
                "How should new updates stay connected to the earlier shared evidence base?",
                topics=["memory"],
            )

            build_topic_view_outputs(
                root=root,
                tree=tree,
                mode="hybrid",
                relation_index={
                    "L1-0325-001": [
                        {
                            "target_obj_id": "L1-0307-001",
                            "relation": "continues",
                            "confidence": 0.88,
                            "shared_concept_keys": ["shared_l1_memory"],
                        }
                    ]
                },
            )

            topic_index = load_topic_index(root)
            self.assertEqual(
                topic_index["L1-0325-001"]["topic_id"],
                topic_index["L1-0307-001"]["topic_id"],
            )

    def test_memory_processing_architecture_alias_links_0429_and_0506(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"

            build_topic_view_outputs(root=root, tree=_topic_assignment_tree(), mode="hybrid")

            topic_index = load_topic_index(root)
            self.assertEqual(
                topic_index["L1-0429-025"]["topic_id"],
                topic_index["L1-0506-009"]["topic_id"],
            )
            self.assertEqual(
                topic_index["L1-0506-009"]["topic_path"],
                ["memory", "memory processing architecture"],
            )

    def test_topic_alias_normalizes_data_fragmentation_spelling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"

            build_topic_view_outputs(root=root, tree=_topic_assignment_tree(), mode="hybrid")

            topic_index = load_topic_index(root)
            self.assertEqual(
                topic_index["L1-0429-030"]["topic_id"],
                topic_index["L1-0506-010"]["topic_id"],
            )
            self.assertEqual(
                topic_index["L1-0506-010"]["topic_path"],
                ["data fragmentation", "data fragmentation"],
            )

    def test_validate_topic_view_flags_banned_and_over_broad_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            topic_tree = {
                "schema_version": 1,
                "generated_at_utc": "2026-05-08T00:00:00Z",
                "source_tree_hash": "test",
                "topic_roots": [
                    {
                        "topic_id": "L3-memory",
                        "level": "L3",
                        "label": "memory",
                        "keywords": ["memory"],
                        "current_state": "",
                        "timeline_digest": [],
                        "event_ids": [],
                        "state_version_ids": [],
                        "children": [
                            {
                                "topic_id": "L2-memory__design-decision",
                                "parent_topic_id": "L3-memory",
                                "level": "L2",
                                "label": "design decision",
                                "keywords": ["memory", "design decision"],
                                "current_state": "",
                                "timeline_digest": [],
                                "event_ids": ["TE-0506-001"],
                                "state_version_ids": ["TS-0506-001"],
                                "object_ids": ["L1-0506-001"],
                            },
                            {
                                "topic_id": "L2-memory__memory-management",
                                "parent_topic_id": "L3-memory",
                                "level": "L2",
                                "label": "memory management",
                                "keywords": ["memory management"],
                                "current_state": "",
                                "timeline_digest": [],
                                "event_ids": ["TE-0506-002", "TE-0506-003", "TE-0506-004"],
                                "state_version_ids": ["TS-0506-002"],
                                "object_ids": ["L1-0506-002", "L1-0506-003", "L1-0506-004"],
                            },
                        ],
                    }
                ],
            }
            topic_index = {
                "L1-0506-001": {
                    "obj_id": "L1-0506-001",
                    "topic_path": ["memory", "design decision"],
                    "topic_id": "L2-memory__design-decision",
                }
            }
            (root / "topic_tree.json").parent.mkdir(parents=True, exist_ok=True)
            (root / "topic_tree.json").write_text(json.dumps(topic_tree), encoding="utf-8")
            (root / "topic_index.json").write_text(json.dumps(topic_index), encoding="utf-8")

            report = validate_topic_view_outputs(
                root=root,
                max_topic_event_count=2,
                expected_links=[],
            )

            self.assertGreaterEqual(report["summary"]["severe_issue_count"], 2)
            issue_codes = {item["code"] for item in report["manual_topic_review_queue"]}
            self.assertIn("banned_topic_label", issue_codes)
            self.assertIn("over_broad_topic", issue_codes)

    def test_validate_topic_view_flags_memory_processing_concept_wrong_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            tree = {
                "tree_version": 1,
                "last_updated_utc": "2026-05-08T00:00:00Z",
                "project_profile": {},
                "phases": [],
                "meetings": [
                    {
                        "meeting_id": "0506",
                        "timestamp": "2026-05-06T00:00:00Z",
                        "meeting_date": "2026-05-06",
                        "source_file": "meeting_recording/transcript/grace/0506.txt",
                        "phase_id": "",
                        "memory_objects": [
                            _obj(
                                "L1-0506-001",
                                "open_issue",
                                (
                                    "A top-down segment-first processing architecture was "
                                    "debated against bottom-up idea unit merging."
                                ),
                                topics=["text splitting", "long context processing"],
                            )
                        ],
                    }
                ],
            }
            refresh_share_mem_outputs(root=root, tree=tree, source_transcript_dir=Path(tmp))
            topic_tree = {
                "schema_version": 1,
                "generated_at_utc": "2026-05-08T00:00:00Z",
                "source_tree_hash": "test",
                "topic_roots": [
                    {
                        "topic_id": "L3-long-context-processing",
                        "level": "L3",
                        "label": "long context processing",
                        "keywords": ["long context processing"],
                        "current_state": "",
                        "timeline_digest": [],
                        "event_ids": ["TE-0506-001"],
                        "state_version_ids": ["TS-0506-001"],
                        "children": [
                            {
                                "topic_id": "L2-long-context-processing__text-splitting",
                                "parent_topic_id": "L3-long-context-processing",
                                "level": "L2",
                                "label": "text splitting",
                                "keywords": ["text splitting"],
                                "current_state": "",
                                "timeline_digest": [],
                                "event_ids": ["TE-0506-001"],
                                "state_version_ids": ["TS-0506-001"],
                                "object_ids": ["L1-0506-001"],
                            }
                        ],
                    }
                ],
            }
            topic_index = {
                "L1-0506-001": {
                    "obj_id": "L1-0506-001",
                    "topic_path": ["long context processing", "text splitting"],
                    "topic_id": "L2-long-context-processing__text-splitting",
                }
            }
            (root / "topic_tree.json").write_text(json.dumps(topic_tree), encoding="utf-8")
            (root / "topic_index.json").write_text(json.dumps(topic_index), encoding="utf-8")

            report = validate_topic_view_outputs(root=root, expected_links=[])

            issue_codes = {item["code"] for item in report["manual_topic_review_queue"]}
            self.assertIn("concept_topic_path_mismatch", issue_codes)


if __name__ == "__main__":
    unittest.main()
