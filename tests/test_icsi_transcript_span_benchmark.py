from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from optimization.long_term_v2.icsi_transcript_span_benchmark import (
    build_transcript_span_benchmark,
    _line_matches,
)


def _write_transcript(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class IcsiTranscriptSpanBenchmarkTests(unittest.TestCase):
    def test_keyword_matching_respects_single_word_boundaries(self) -> None:
        self.assertFalse(_line_matches("The model performance changed.", ("form",)))
        self.assertTrue(_line_matches("The participant form changed.", ("form",)))
        self.assertTrue(_line_matches("We discussed close microphone placement.", ("close microphone",)))

    def test_builds_annotation_ready_gold_from_transcript_spans_not_l1_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcripts = root / "meeting_recording" / "transcript" / "ISCI"
            _write_transcript(
                transcripts / "Bmr001.txt",
                [
                    "[me001]: The close microphone signal is cleaner than the far microphone.",
                    "[me002]: Delay-and-sum beamforming is still useful as a comparison.",
                    "[me001]: We should keep both microphone notes for later processing.",
                ],
            )
            _write_transcript(
                transcripts / "Bmr024.txt",
                [
                    "[me003]: Later audio processing still depends on the close microphone choice.",
                    "[me004]: We need to revisit beamforming and channel alignment.",
                ],
            )
            out = root / "optimization" / "reports" / "transcript_span"

            report = build_transcript_span_benchmark(
                transcript_root=transcripts,
                out_dir=out,
                source_through_meeting_id="Bmr023",
                max_questions=3,
                clean=True,
            )

            self.assertEqual(report["status"], "annotation_ready_needs_human_review")
            self.assertEqual(report["query_count"], 1)
            rows = [
                json.loads(line)
                for line in (out / "transcript_span_queries.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["primary_gold_source"], "transcript_span")
            self.assertEqual(row["l1_gold_policy"], "diagnostic_alignment_only")
            self.assertEqual(row["annotation_status"], "needs_human_review")
            self.assertEqual(row["held_out_meeting_id"], "Bmr024")
            self.assertEqual(row["trigger_span"]["meeting_id"], "Bmr024")
            self.assertEqual(row["gold_transcript_spans"][0]["meeting_id"], "Bmr001")
            self.assertIn("line_start", row["gold_transcript_spans"][0])
            self.assertIn("close microphone", row["gold_transcript_spans"][0]["text_preview"])
            self.assertEqual(row["optional_alignment"]["expected_l1_ids"], [])

    def test_report_blocks_when_no_future_trigger_has_source_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcripts = root / "meeting_recording" / "transcript" / "ISCI"
            _write_transcript(transcripts / "Bmr001.txt", ["[me001]: The team discussed consent forms."])
            _write_transcript(transcripts / "Bmr024.txt", ["[me002]: A later meeting discussed unrelated lunch plans."])

            report = build_transcript_span_benchmark(
                transcript_root=transcripts,
                out_dir=root / "optimization" / "reports" / "transcript_span",
                source_through_meeting_id="Bmr023",
                clean=True,
            )

            self.assertEqual(report["status"], "blocked_no_supported_transcript_spans")
            self.assertEqual(report["query_count"], 0)


if __name__ == "__main__":
    unittest.main()
