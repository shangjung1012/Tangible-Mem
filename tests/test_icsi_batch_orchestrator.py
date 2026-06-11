from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from share_mem.run_icsi_batch import (
    BatchConfig,
    _load_status,
    build_bridge_command,
    build_filtered_share_tree,
    config_from_args,
    discover_transcripts,
    parse_args,
    prepare_transcript_input,
    run_batch,
    validate_output_root_safety,
)


class ICSIBatchOrchestratorTests(unittest.TestCase):
    def test_bridge_command_uses_icsi_defaults_and_one_transcript(self) -> None:
        config = BatchConfig(
            transcript_dir=Path("meeting_recording/transcript/ISCI"),
            output_root=Path("share_mem_experiments/icsi_batch_test"),
            model="gemini-2.5-pro",
        )

        command = build_bridge_command(config, Path("Bdb001.txt"))

        self.assertIn("-m", command)
        self.assertIn("share_mem.l1.bridge", command)
        self.assertIn("--transcript", command)
        self.assertIn("Bdb001.txt", command)
        self.assertIn("--tree", command)
        self.assertIn(str(config.share_mem_root / "tree.json"), command)
        self.assertIn("--dataset-profile", command)
        self.assertIn("isci", command)
        self.assertIn("--content-language", command)
        self.assertIn("english", command)
        self.assertIn("--multi-agent-window-size", command)
        self.assertIn("120", command)
        self.assertIn("--include-legacy-type", command)

    def test_prepare_transcript_input_writes_line_limited_experiment_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Bmr001.txt"
            source.write_text("one\n二\nthree\nfour\n", encoding="utf-8")

            prepared = prepare_transcript_input(
                transcript_path=source,
                input_root=root / "input_transcripts",
                line_limit=3,
            )

            self.assertEqual(prepared.name, "Bmr001_first3.txt")
            self.assertEqual(prepared.read_text(encoding="utf-8"), "one\n二\nthree\n")
            self.assertEqual(source.read_text(encoding="utf-8"), "one\n二\nthree\nfour\n")

    def test_output_root_safety_rejects_canonical_share_mem(self) -> None:
        with self.assertRaises(ValueError):
            validate_output_root_safety(Path("share_mem"))
        with self.assertRaises(ValueError):
            validate_output_root_safety(Path("share_mem/icsi_bad_output"))

    def test_output_base_and_run_id_resolve_dataset_run_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = parse_args(
                [
                    "--transcript-dir",
                    str(Path(tmp) / "transcripts"),
                    "--output-base",
                    str(Path(tmp) / "memory_outputs"),
                    "--run-id",
                    "bmr012_016_first360_20260605",
                    "--line-limit",
                    "360",
                    "--dry-run",
                ]
            )

            config = config_from_args(args)

            self.assertEqual(
                config.output_root,
                Path(tmp)
                / "memory_outputs"
                / "icsi"
                / "runs"
                / "bmr_first360_bmr012_016_first360_20260605",
            )

    def test_discover_transcripts_start_after_then_max_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript_dir = Path(tmp) / "transcripts"
            transcript_dir.mkdir()
            for name in [
                "Bmr010.txt",
                "Bmr011.txt",
                "Bmr012.txt",
                "Bmr013.txt",
                "Bmr014.txt",
                "Bmr015.txt",
                "Bmr016.txt",
                "Bmr018.txt",
            ]:
                (transcript_dir / name).write_text("[me001]: hello\n", encoding="utf-8")
            config = BatchConfig(
                transcript_dir=transcript_dir,
                output_root=Path(tmp) / "out",
                model="gemini-2.5-pro",
                transcript_glob="Bmr*.txt",
                start_after="Bmr011.txt",
                max_files=5,
            )

            selected = discover_transcripts(config)

            self.assertEqual(
                [path.name for path in selected],
                ["Bmr012.txt", "Bmr013.txt", "Bmr014.txt", "Bmr015.txt", "Bmr016.txt"],
            )

    def test_discover_transcripts_start_after_requires_existing_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript_dir = Path(tmp) / "transcripts"
            transcript_dir.mkdir()
            (transcript_dir / "Bmr012.txt").write_text("[me001]: hello\n", encoding="utf-8")
            config = BatchConfig(
                transcript_dir=transcript_dir,
                output_root=Path(tmp) / "out",
                model="gemini-2.5-pro",
                transcript_glob="Bmr*.txt",
                start_after="Bmr011.txt",
                max_files=5,
            )

            with self.assertRaisesRegex(ValueError, "start-after"):
                discover_transcripts(config)

    def test_dry_run_writes_per_file_status_without_tree_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript_dir = root / "transcripts"
            transcript_dir.mkdir()
            (transcript_dir / "Bdb001.txt").write_text("[me001]: hello\n", encoding="utf-8")
            (transcript_dir / "Bed002.txt").write_text("[me002]: world\n", encoding="utf-8")
            config = BatchConfig(
                transcript_dir=transcript_dir,
                output_root=root / "out",
                model="gemini-2.5-pro",
                dry_run=True,
                line_limit=1,
            )

            status = run_batch(config)

            self.assertEqual(status["summary"]["dry_run_count"], 2)
            self.assertEqual([row["status"] for row in status["runs"]], ["dry_run", "dry_run"])
            self.assertTrue((root / "out" / "batch_status.json").exists())
            self.assertFalse((root / "out" / "share_mem" / "tree.json").exists())

    def test_dry_run_with_output_base_writes_status_under_resolved_run_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript_dir = root / "transcripts"
            transcript_dir.mkdir()
            (transcript_dir / "Bmr012.txt").write_text("[me001]: hello\n", encoding="utf-8")
            args = parse_args(
                [
                    "--transcript-dir",
                    str(transcript_dir),
                    "--output-base",
                    str(root / "memory_outputs"),
                    "--run-id",
                    "bmr012_016_first360_20260605",
                    "--transcript-glob",
                    "Bmr*.txt",
                    "--line-limit",
                    "360",
                    "--dry-run",
                ]
            )

            config = config_from_args(args)
            status = run_batch(config)

            expected_root = (
                root
                / "memory_outputs"
                / "icsi"
                / "runs"
                / "bmr_first360_bmr012_016_first360_20260605"
            )
            self.assertEqual(config.output_root, expected_root)
            self.assertEqual(status["summary"]["dry_run_count"], 1)
            self.assertTrue((expected_root / "batch_status.json").exists())
            self.assertTrue((expected_root / "run_manifest.json").exists())

    def test_dry_run_records_effective_vertex_runtime_in_status_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript_dir = root / "transcripts"
            transcript_dir.mkdir()
            (transcript_dir / "Bmr011.txt").write_text("[me001]: hello\n", encoding="utf-8")
            config = BatchConfig(
                transcript_dir=transcript_dir,
                output_root=root / "out",
                model="gemini-2.5-pro",
                dry_run=True,
            )

            with (
                patch("share_mem.run_icsi_batch.ensure_env_loaded"),
                patch.dict(
                    "os.environ",
                    {
                        "GOOGLE_GENAI_USE_VERTEXAI": "true",
                        "GOOGLE_CLOUD_PROJECT": "icsirun2",
                        "GOOGLE_CLOUD_LOCATION": "global",
                        "GOOGLE_APPLICATION_CREDENTIALS": "C:/Users/name/application_default_credentials.json",
                        "GEMINI_MODEL": "gemini-2.5-pro",
                    },
                    clear=True,
                ),
            ):
                status = run_batch(config)

            runtime = status["runtime_environment"]
            self.assertEqual(runtime["google_cloud_project"], "icsirun2")
            self.assertEqual(runtime["google_cloud_location"], "global")
            self.assertTrue(runtime["vertexai_enabled"])
            self.assertTrue(runtime["application_credentials_configured"])
            self.assertEqual(runtime["application_credentials_file"], "application_default_credentials.json")

            manifest = json.loads((root / "out" / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["config"]["runtime_environment"]["google_cloud_project"],
                "icsirun2",
            )


    def test_batch_stops_after_target_success_count_without_starting_next_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript_dir = root / "transcripts"
            transcript_dir.mkdir()
            for name in ["Bmr001.txt", "Bmr002.txt", "Bmr003.txt"]:
                (transcript_dir / name).write_text("[me001]: hello\n", encoding="utf-8")
            config = BatchConfig(
                transcript_dir=transcript_dir,
                output_root=root / "out",
                model="gemini-2.5-pro",
                target_success_count=2,
                continue_on_failure=True,
            )

            with (
                patch("share_mem.run_icsi_batch._run_command", return_value=("succeeded", 0, "")),
                patch(
                    "share_mem.run_icsi_batch._refresh_share_mem",
                    return_value={"meeting_count": 1, "object_count": 1},
                ),
                patch(
                    "share_mem.run_icsi_batch._run_validation",
                    return_value={"review_gate_summary": {}, "filtered_manifest": {}},
                ),
            ):
                status = run_batch(config)

            self.assertEqual(status["summary"]["succeeded_count"], 2)
            self.assertTrue(status["summary"]["target_success_reached"])
            self.assertEqual([row["meeting_source"] for row in status["runs"]], ["Bmr001.txt", "Bmr002.txt"])

    def test_batch_status_loader_accepts_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch_status.json"
            path.write_text('\ufeff{"schema_version": 1, "runs": []}', encoding="utf-8")

            self.assertEqual(_load_status(path)["runs"], [])

    def test_build_filtered_share_tree_keeps_raw_tree_unchanged(self) -> None:
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-06-05T00:00:00Z",
            "meetings": [
                {
                    "meeting_id": "Bmr001",
                    "timestamp": "2026-06-05T00:00:00Z",
                    "meeting_date": "",
                    "source_file": "Bmr001.txt",
                    "phase_id": "",
                    "memory_objects": [
                        {"obj_id": "L1-Bmr001-001", "content": "drop inventory"},
                        {"obj_id": "L1-Bmr001-002", "content": "keep protocol"},
                    ],
                }
            ],
        }
        gate = {"filtered_candidate_obj_ids": ["L1-Bmr001-002"]}

        filtered = build_filtered_share_tree(tree, gate)

        self.assertEqual(
            [obj["obj_id"] for obj in filtered["meetings"][0]["memory_objects"]],
            ["L1-Bmr001-002"],
        )
        self.assertEqual(
            [obj["obj_id"] for obj in tree["meetings"][0]["memory_objects"]],
            ["L1-Bmr001-001", "L1-Bmr001-002"],
        )
        self.assertEqual(filtered["source_view"]["raw_tree_object_count"], 2)
        self.assertEqual(filtered["source_view"]["filtered_object_count"], 1)


if __name__ == "__main__":
    unittest.main()
