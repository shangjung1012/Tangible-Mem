from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SHORT_TERM_DIR = REPO_ROOT / "short_term"
sys.path.insert(0, str(SHORT_TERM_DIR))
for module_name in ("storage.transcript_store",):
    sys.modules.pop(module_name, None)

from storage.transcript_store import (  # noqa: E402
    import_transcript_to_sqlite,
    load_transcript_lines,
    load_transcript_overview,
)


class ShortTermTranscriptStoreTests(unittest.TestCase):
    def test_import_and_read_line_ranges(self) -> None:
        transcript = """
[SPEAKER_00]: 第一段內容
[SPEAKER_01]: 第二段內容
沒有 speaker 的內容
[SPEAKER_00]: 第四段內容
""".strip()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "transcripts.db"
            line_count = import_transcript_to_sqlite(
                db_path=db_path,
                meeting_id="0422",
                source_file="meeting_recording/transcript/grace/0422.txt",
                transcript=transcript,
            )

            self.assertEqual(line_count, 4)

            overview = load_transcript_overview(db_path, "0422", preview_limit=2)
            self.assertTrue(overview["ok"])
            self.assertEqual(overview["line_count"], 4)
            self.assertEqual(overview["first_lines"][0]["speaker"], "SPEAKER_00")
            self.assertEqual(overview["last_lines"][-1]["line_number"], 4)

            page = load_transcript_lines(
                db_path=db_path,
                meeting_id="0422",
                start_line=2,
                end_line=3,
                limit=10,
            )
            self.assertTrue(page["ok"])
            self.assertEqual(page["returned_count"], 2)
            self.assertEqual(
                [row["line_number"] for row in page["items"]],
                [2, 3],
            )
            self.assertEqual(page["items"][0]["speaker"], "SPEAKER_01")
            self.assertEqual(page["items"][1]["text"], "沒有 speaker 的內容")

    def test_read_limit_caps_range(self) -> None:
        transcript = "\n".join(f"[S]: line {index}" for index in range(1, 6))

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "transcripts.db"
            import_transcript_to_sqlite(
                db_path=db_path,
                meeting_id="m",
                source_file="m.txt",
                transcript=transcript,
            )

            page = load_transcript_lines(
                db_path=db_path,
                meeting_id="m",
                start_line=1,
                end_line=5,
                limit=2,
            )

            self.assertEqual(page["end_line"], 2)
            self.assertEqual(page["returned_count"], 2)
            self.assertTrue(page["has_more"])
            self.assertEqual(page["next_start_line"], 3)

    def test_import_splits_icsi_participant_id_and_text(self) -> None:
        transcript = "[me011]: OK, so we're live.\n[fe016] : Right."

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "transcripts.db"
            import_transcript_to_sqlite(
                db_path=db_path,
                meeting_id="Bmr001",
                source_file="meeting_recording/transcript/ISCI/Bmr001.txt",
                transcript=transcript,
            )

            page = load_transcript_lines(
                db_path=db_path,
                meeting_id="Bmr001",
                start_line=1,
                limit=2,
            )

            self.assertEqual(page["items"][0]["speaker"], "me011")
            self.assertEqual(page["items"][0]["text"], "OK, so we're live.")
            self.assertEqual(page["items"][1]["speaker"], "fe016")
            self.assertEqual(page["items"][1]["text"], "Right.")


if __name__ == "__main__":
    unittest.main()
