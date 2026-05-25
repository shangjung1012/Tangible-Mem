from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from share_mem.run_icsi_batch import (
    BatchConfig,
    build_bridge_command,
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


if __name__ == "__main__":
    unittest.main()
