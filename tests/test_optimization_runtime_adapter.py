from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import memory_context


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class OptimizationRuntimeExportTests(unittest.TestCase):
    def _write_v2_run(self, root: Path) -> None:
        _write_json(
            root / "input_snapshot" / "tree.json",
            {
                "meetings": [
                    {
                        "meeting_id": "T001",
                        "meeting_date": "2026-01-01",
                        "memory_objects": [
                            {
                                "obj_id": "L1-T001-001",
                                "type": "decision",
                                "content": "The team chose evidence-first retrieval.",
                                "evidence": "We should retrieve evidence before topic summaries.",
                                "importance": 0.8,
                                "related_topics": ["retrieval"],
                                "related_obj_ids": [],
                            }
                        ],
                    }
                ]
            },
        )
        _write_json(
            root / "l2" / "l2_view.json",
            {
                "schema_version": 1,
                "l2_nodes": [
                    {
                        "l2_id": "L2-evidence-first-retrieval",
                        "label": "evidence-first retrieval",
                        "current_state": "The active retrieval design starts from L1 evidence.",
                        "linked_obj_ids": ["L1-T001-001"],
                        "timeline_digest": [
                            {
                                "meeting_id": "T001",
                                "meeting_date": "2026-01-01",
                                "obj_id": "L1-T001-001",
                                "summary": "The team chose evidence-first retrieval.",
                            }
                        ],
                    }
                ],
            },
        )
        _write_json(
            root / "l2" / "l2_index.json",
            {
                "L1-T001-001": {
                    "obj_id": "L1-T001-001",
                    "l2_id": "L2-evidence-first-retrieval",
                    "l2_label": "evidence-first retrieval",
                    "confidence": 0.92,
                }
            },
        )
        _write_json(
            root / "l3" / "l3_view.json",
            {
                "schema_version": 1,
                "l3_parents": [
                    {
                        "l3_id": "L3-retrieval-design",
                        "label": "retrieval design",
                        "source_l2_id": "L2-evidence-first-retrieval",
                        "child_l2_nodes": [
                            {
                                "child_l2_id": "L2-retrieval-design-evidence-first",
                                "label": "evidence-first retrieval",
                                "current_state": "Evidence-first retrieval is the current design.",
                                "linked_obj_ids": ["L1-T001-001"],
                                "timeline_digest": [
                                    {
                                        "meeting_id": "T001",
                                        "meeting_date": "2026-01-01",
                                        "obj_id": "L1-T001-001",
                                        "summary": "The team chose evidence-first retrieval.",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        )
        _write_json(
            root / "l3" / "l3_index.json",
            {
                "L1-T001-001": {
                    "parent_l3_id": "L3-retrieval-design",
                    "parent_l3_label": "retrieval design",
                    "child_l2_id": "L2-retrieval-design-evidence-first",
                    "child_l2_label": "evidence-first retrieval",
                }
            },
        )

    def test_export_runtime_view_writes_recall_compatible_sidecars(self) -> None:
        from optimization.long_term_v2.export_runtime_view import export_runtime_view

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_v2_run(root)

            manifest = export_runtime_view(root, clean=True)

            runtime_l3_view = json.loads(
                (root / "runtime" / "l3" / "l3_view.json").read_text(encoding="utf-8")
            )
            runtime_l3_index = json.loads(
                (root / "runtime" / "l3" / "l3_index.json").read_text(encoding="utf-8")
            )

            self.assertEqual(manifest["runtime_schema"], "canonical_recall_v1")
            self.assertEqual(runtime_l3_view["l3_nodes"][0]["l3_id"], "L3-retrieval-design")
            self.assertEqual(
                runtime_l3_view["l3_nodes"][0]["promoted_from_l2_id"],
                "L2-evidence-first-retrieval",
            )
            self.assertEqual(
                runtime_l3_view["l3_nodes"][0]["child_l2_nodes"][0]["l2_id"],
                "L2-retrieval-design-evidence-first",
            )
            self.assertEqual(runtime_l3_index["L1-T001-001"]["l3_id"], "L3-retrieval-design")
            self.assertTrue((root / "runtime" / "l2" / "l2_secondary_links.json").exists())
            self.assertTrue((root / "runtime" / "l3" / "l3_promotions.json").exists())


class MemoryContextBackendTests(unittest.TestCase):
    def test_default_long_term_backend_uses_canonical_paths(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LONG_TERM_BACKEND", None)
            paths = memory_context.resolve_long_term_runtime_paths()

        self.assertEqual(paths["backend"], "canonical")
        self.assertEqual(paths["tree_path"], memory_context.LONG_TERM_TREE_PATH)
        self.assertEqual(paths["l2_view_path"], memory_context.LONG_TERM_L2_VIEW_PATH)

    def test_optimization_backend_resolves_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_root = Path(temp_dir)
            for path in [
                run_root / "runtime" / "input_snapshot" / "tree.json",
                run_root / "runtime" / "l2" / "l2_index.json",
                run_root / "runtime" / "l2" / "l2_view.json",
                run_root / "runtime" / "l2" / "l2_secondary_links.json",
                run_root / "runtime" / "l3" / "l3_promotions.json",
                run_root / "runtime" / "l3" / "l3_view.json",
                run_root / "runtime" / "l3" / "l3_index.json",
            ]:
                _write_json(path, {})

            with patch.dict(
                os.environ,
                {
                    "LONG_TERM_BACKEND": "optimization_v2",
                    "OPTIMIZATION_V2_RUN_ROOT": str(run_root),
                },
                clear=False,
            ):
                paths = memory_context.resolve_long_term_runtime_paths()

            self.assertEqual(paths["backend"], "optimization_v2")
            self.assertEqual(paths["tree_path"], run_root / "runtime" / "input_snapshot" / "tree.json")
            self.assertEqual(paths["l3_view_path"], run_root / "runtime" / "l3" / "l3_view.json")

    def test_optimization_backend_missing_runtime_falls_back_to_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "LONG_TERM_BACKEND": "optimization_v2",
                    "OPTIMIZATION_V2_RUN_ROOT": temp_dir,
                },
                clear=False,
            ):
                paths = memory_context.resolve_long_term_runtime_paths()

        self.assertEqual(paths["backend"], "canonical")
        self.assertEqual(paths["fallback_reason"], "optimization_v2_runtime_incomplete")


if __name__ == "__main__":
    unittest.main()
