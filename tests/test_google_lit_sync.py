import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


class GoogleLitSyncTests(unittest.TestCase):
    def test_export_writes_doc_and_sheet_files(self):
        from tools import google_lit_sync

        class FakeDownloader:
            def __call__(self, url):
                if "document" in url:
                    return b"notes text\n"
                if "spreadsheets" in url:
                    return b'TRUE,"Title","","@misc{Key,title={Title},year={2026}}"\n'
                raise AssertionError(url)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = google_lit_sync.export_sources(root, downloader=FakeDownloader(), postprocess=False)

            self.assertEqual(result.doc_bytes, 11)
            self.assertIn("notes text", (root / "paper" / "source-notes" / "related-paper-notes.txt").read_text())
            self.assertIn("Title", (root / "paper" / "lit" / "reference.csv").read_text())

    def test_append_sheet_dry_run_filters_duplicates_and_preserves_false_selected(self):
        from tools import google_lit_sync

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "paper" / "lit").mkdir(parents=True)
            (root / "paper" / "lit" / "reference.csv").write_text(
                'TRUE,"Already Known","https://doi.org/10.1234/known",""\n',
                encoding="utf-8",
            )
            (root / "paper" / "references.bib").write_text(
                "@article{Known2026, title={Known Bib}, doi={10.5555/bib}, year={2026}}\n",
                encoding="utf-8",
            )
            candidate = root / "paper" / "lit" / "candidate_papers.csv"
            candidate.write_text(
                "selected,title,doi_or_url,bibtex,source_query,relevance_to_sections,status,notes\n"
                'True,"Already Known","https://doi.org/10.1234/known",,"q","s","candidate","skip"\n'
                'False,"New Paper","https://doi.org/10.9999/new",,"q","s","candidate","keep"\n',
                encoding="utf-8",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = google_lit_sync.append_sheet(root, input_path=candidate.relative_to(root), apply=False)

            self.assertEqual(exit_code, 0)
            self.assertIn("DRY RUN: 1 sheet row", output.getvalue())
            self.assertIn("selected=False; title=New Paper", output.getvalue())
            self.assertIn("Skipped 1 duplicate", output.getvalue())

    def test_append_sheet_apply_uses_values_append(self):
        from tools import google_lit_sync

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "paper" / "lit").mkdir(parents=True)
            (root / "paper" / "lit" / "reference.csv").write_text("", encoding="utf-8")
            (root / "paper" / "references.bib").write_text("", encoding="utf-8")
            candidate = root / "paper" / "lit" / "candidate_papers.csv"
            candidate.write_text(
                "selected,title,doi_or_url,bibtex,source_query,relevance_to_sections,status,notes\n"
                'False,"New Paper","https://doi.org/10.9999/new",,"q","s","candidate","keep"\n',
                encoding="utf-8",
            )

            calls = []

            def fake_append(spreadsheet_id, append_range, values, token):
                calls.append((spreadsheet_id, append_range, values, token))
                return {"updates": {"updatedRange": "Sheet1!A2:H2"}}

            with patch.object(google_lit_sync, "_sheet_title_for_gid", return_value="Sheet1"):
                with patch.object(google_lit_sync, "_append_sheet_values", side_effect=fake_append):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        exit_code = google_lit_sync.append_sheet(
                            root,
                            input_path=candidate.relative_to(root),
                            apply=True,
                            token="token",
                        )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], "'Sheet1'!A:H")
            self.assertEqual(calls[0][2][0][0], "False")
            self.assertIn("APPLIED sheet append: 1 row", output.getvalue())

    def test_append_doc_dry_run_skips_duplicate_note(self):
        from tools import google_lit_sync

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "paper" / "source-notes").mkdir(parents=True)
            note = "## Candidate\n\nAlready there."
            (root / "paper" / "source-notes" / "related-paper-notes.txt").write_text(note, encoding="utf-8")
            candidate_note = root / "paper" / "source-notes" / "candidate_lit_notes.md"
            candidate_note.write_text(note, encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = google_lit_sync.append_doc(root, input_path=candidate_note.relative_to(root), apply=False)

            self.assertEqual(exit_code, 0)
            self.assertIn("Skipped doc append: duplicate note text", output.getvalue())

    def test_append_doc_apply_uses_batch_update(self):
        from tools import google_lit_sync

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "paper" / "source-notes").mkdir(parents=True)
            candidate_note = root / "paper" / "source-notes" / "candidate_lit_notes.md"
            candidate_note.write_text("## Candidate\n\nFresh note.", encoding="utf-8")

            calls = []

            def fake_append(doc_id, text, token):
                calls.append((doc_id, text, token))
                return {"replies": [{}]}

            with patch.object(google_lit_sync, "_append_doc_text", side_effect=fake_append):
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = google_lit_sync.append_doc(
                        root,
                        input_path=candidate_note.relative_to(root),
                        apply=True,
                        token="token",
                    )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(calls), 1)
            self.assertIn("Fresh note", calls[0][1])
            self.assertIn("APPLIED doc append", output.getvalue())


if __name__ == "__main__":
    unittest.main()
