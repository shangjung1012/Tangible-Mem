from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from optimization.output_roots import resolve_memory_run_root
from optimization.combine_share_mem_runs import (
    combine_archive_filtered_share_mem,
    combine_share_mem_roots,
    config_output_root,
    parse_args,
)
from optimization.run_grace_memory_build import main as grace_memory_build_main
from optimization.run_manifest import write_run_manifest
from share_mem.store import refresh_share_mem_outputs


class MemoryOutputRootTests(unittest.TestCase):
    def _write_fixture_share_mem(
        self,
        root: Path,
        *,
        meeting_id: str,
        obj_id: str,
        content: str,
    ) -> None:
        refresh_share_mem_outputs(
            root=root,
            tree={
                "tree_version": 1,
                "last_updated_utc": "2026-06-05T00:00:00Z",
                "project_profile": {},
                "phases": [],
                "meetings": [
                    {
                        "meeting_id": meeting_id,
                        "timestamp": "2026-06-05T00:00:00Z",
                        "meeting_date": "2026-06-05",
                        "source_file": f"{meeting_id}.txt",
                        "phase_id": "",
                        "memory_objects": [
                            {
                                "obj_id": obj_id,
                                "type": "finding",
                                "content": content,
                                "importance": 0.7,
                                "evidence": content,
                                "related_topics": ["recording data quality"],
                                "related_obj_ids": [],
                                "legacy_type": "result",
                            }
                        ],
                    }
                ],
            },
            source_transcript_dir=None,
        )

    def test_resolve_icsi_run_root_stays_under_memory_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = resolve_memory_run_root(
                base_root=Path(tmp) / "memory_outputs",
                dataset="icsi",
                run_kind="bmr_first360",
                run_id="batch01_20260605",
            )

            self.assertEqual(
                root,
                Path(tmp)
                / "memory_outputs"
                / "icsi"
                / "runs"
                / "bmr_first360_batch01_20260605",
            )

    def test_reject_canonical_output_paths(self) -> None:
        for bad_root in [Path("share_mem"), Path("long_term"), Path("share_mem/icsi")]:
            with self.subTest(bad_root=str(bad_root)):
                with self.assertRaisesRegex(ValueError, "canonical"):
                    resolve_memory_run_root(
                        base_root=bad_root,
                        dataset="grace",
                        run_kind="l1",
                        run_id="bad",
                    )

    def test_write_run_manifest_records_source_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            source.write_text("hello\n", encoding="utf-8")

            manifest = write_run_manifest(
                run_root=root / "run",
                dataset="icsi",
                run_kind="bmr_first360",
                source_paths=[source],
                config={"line_limit": 360},
            )

            loaded = json.loads((root / "run" / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(loaded["dataset"], "icsi")
            self.assertEqual(loaded["run_kind"], "bmr_first360")
            self.assertEqual(loaded["config"]["line_limit"], 360)
            self.assertIn(str(source.resolve()), loaded["source_hashes"])
            self.assertEqual(manifest, loaded)

    def test_combine_share_mem_roots_writes_effective_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_a = root / "batch_a" / "filtered_share_mem"
            source_b = root / "batch_b" / "filtered_share_mem"
            self._write_fixture_share_mem(
                source_a,
                meeting_id="Bmr001_first360",
                obj_id="L1-Bmr001-001",
                content="A durable recording procedure was discussed.",
            )
            self._write_fixture_share_mem(
                source_b,
                meeting_id="Bmr007_first360",
                obj_id="L1-Bmr007-001",
                content="A durable headset quality issue was discussed.",
            )

            report = combine_share_mem_roots(
                source_roots=[source_a, source_b],
                output_root=root / "combined",
                clean=True,
            )

            manifest = json.loads((root / "combined" / "share_mem_effective" / "manifest.json").read_text(encoding="utf-8"))
            tree = json.loads((root / "combined" / "share_mem_effective" / "tree.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["meeting_count"], 2)
            self.assertEqual(manifest["object_count"], 2)
            self.assertEqual(report["summary"]["meeting_count"], 2)
            self.assertEqual(report["summary"]["object_count"], 2)
            self.assertEqual(tree["source_view"]["source"], "combined_effective_share_mem")
            self.assertTrue(tree["source_view"]["sidecar_only"])

    def test_combine_share_mem_roots_rejects_duplicate_obj_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_a = root / "batch_a" / "filtered_share_mem"
            source_b = root / "batch_b" / "filtered_share_mem"
            self._write_fixture_share_mem(
                source_a,
                meeting_id="Bmr001_first360",
                obj_id="L1-DUP",
                content="First object.",
            )
            self._write_fixture_share_mem(
                source_b,
                meeting_id="Bmr007_first360",
                obj_id="L1-DUP",
                content="Duplicate object.",
            )

            with self.assertRaisesRegex(ValueError, "Duplicate obj_id"):
                combine_share_mem_roots(
                    source_roots=[source_a, source_b],
                    output_root=root / "combined",
                    clean=True,
                )

    def test_combine_archive_filtered_share_mem_uses_import_manifest_filtered_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "memory_outputs" / "icsi" / "archive_imports"
            batch_a = archive / "batch_a"
            batch_b = archive / "batch_b"
            self._write_fixture_share_mem(
                batch_a / "share_mem",
                meeting_id="Bmr001_first360",
                obj_id="L1-RAW-A",
                content="Raw object should not be merged.",
            )
            self._write_fixture_share_mem(
                batch_a / "filtered_share_mem",
                meeting_id="Bmr001_first360",
                obj_id="L1-FILTERED-A",
                content="Filtered object should be merged.",
            )
            self._write_fixture_share_mem(
                batch_b / "share_mem",
                meeting_id="Bmr007_first360",
                obj_id="L1-RAW-B",
                content="Raw object should not be merged.",
            )
            self._write_fixture_share_mem(
                batch_b / "filtered_share_mem",
                meeting_id="Bmr007_first360",
                obj_id="L1-FILTERED-B",
                content="Filtered object should be merged.",
            )
            import_manifest = archive / "import_manifest.json"
            import_manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "imports": [
                            {"imported_path": str(batch_a), "meeting_count": 1},
                            {"imported_path": str(batch_b), "meeting_count": 1},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = combine_archive_filtered_share_mem(
                import_manifest=import_manifest,
                output_root=root / "memory_outputs" / "icsi" / "runs" / "combined",
                clean=True,
            )

            effective_root = root / "memory_outputs" / "icsi" / "runs" / "combined" / "share_mem_effective"
            l1_index = json.loads((effective_root / "l1_index.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["meeting_count"], 2)
            self.assertEqual(report["summary"]["object_count"], 2)
            self.assertEqual(set(l1_index), {"L1-FILTERED-A", "L1-FILTERED-B"})
            self.assertNotIn("L1-RAW-A", l1_index)
            self.assertTrue(report["source_policy"]["filtered_share_mem_required"])

    def test_combine_cli_output_base_is_not_bmr_specific(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = parse_args(
                [
                    "--archive-import-manifest",
                    "memory_outputs/icsi/archive_imports/import_manifest.json",
                    "--output-base",
                    str(Path(tmp) / "memory_outputs"),
                    "--dataset",
                    "conversation",
                    "--run-kind",
                    "mentor_probe_combined",
                    "--run-id",
                    "demo001",
                ]
            )

            output_root = config_output_root(args)

            self.assertEqual(
                output_root,
                Path(tmp) / "memory_outputs" / "conversation" / "runs" / "mentor_probe_combined_demo001",
            )

    def test_grace_memory_build_defaults_to_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                grace_memory_build_main(
                    [
                        "--output-base",
                        str(Path(tmp) / "memory_outputs"),
                        "--run-id",
                        "grace_rebuild_20260605",
                    ]
                )

            output = stdout.getvalue()
            self.assertIn("DRY RUN", output)
            self.assertIn("memory_outputs", output)
            self.assertIn("grace/runs/grace_full_grace_rebuild_20260605", output.replace("\\", "/"))
            self.assertIn("build_tree.py", output)
            self.assertIn("build_view.py", output)
            self.assertIn("validate_view.py", output)

    def test_grace_memory_build_script_runs_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    "optimization/run_grace_memory_build.py",
                    "--output-base",
                    str(Path(tmp) / "memory_outputs"),
                    "--run-id",
                    "grace_rebuild_20260605",
                ],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("DRY RUN", completed.stdout)

    def test_icsi_batch_script_help_runs_directly(self) -> None:
        completed = subprocess.run(
            [sys.executable, "share_mem/run_icsi_batch.py", "--help"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--output-base", completed.stdout)


if __name__ == "__main__":
    unittest.main()
