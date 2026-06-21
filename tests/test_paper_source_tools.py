import io
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path


class ExtractBibFromReferenceCsvTests(unittest.TestCase):
    def test_extracts_unique_selected_bibtex_and_records_missing_selected_rows(self):
        from tools import extract_bib_from_reference_csv as extractor

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lit_dir = root / "paper" / "lit"
            lit_dir.mkdir(parents=True)
            (root / "paper" / "source-notes").mkdir(parents=True)
            bib_entry = textwrap.dedent(
                r"""
                @article{Chen2026Memory,
                  title={Layered Memory \u4e2d\u6587},
                  author={Chen, I.},
                  year={2026}
                }
                """
            ).strip()
            csv_text = (
                "selected,title,bibtex\n"
                f'True,"Inspectable memory","{bib_entry}"\n'
                'False,"Ignored row","@misc{Ignore2026,title={No}}"\n'
                'True,"Missing BibTeX",""\n'
                f'True,"Duplicate memory","{bib_entry}"\n'
            )
            (lit_dir / "reference.csv").write_text(csv_text, encoding="utf-8", newline="")

            result = extractor.extract_bib_from_reference_csv(root)

            self.assertEqual(result.entry_count, 1)
            self.assertEqual(result.missing_bibtex_count, 1)
            references = (root / "paper" / "references.bib").read_text(encoding="utf-8")
            self.assertIn("@article{Chen2026Memory", references)
            self.assertIn(r"\u4e2d\u6587", references)
            self.assertNotIn("Ignore2026", references)
            todo = (lit_dir / "missing_bibtex_todo.md").read_text(encoding="utf-8")
            self.assertIn("Missing BibTeX", todo)

    def test_extract_preserves_existing_manually_fetched_bibtex_entries(self):
        from tools import extract_bib_from_reference_csv as extractor

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lit_dir = root / "paper" / "lit"
            lit_dir.mkdir(parents=True)
            (root / "paper" / "references.bib").write_text(
                "@misc{Manual2026,\n  title={Manual fetched entry},\n  year={2026}\n}\n",
                encoding="utf-8",
            )
            (lit_dir / "reference.csv").write_text(
                'TRUE,"CSV paper","","@misc{Csv2026,title={CSV paper},year={2026}}"\n',
                encoding="utf-8",
                newline="",
            )

            extractor.extract_bib_from_reference_csv(root)

            references = (root / "paper" / "references.bib").read_text(encoding="utf-8")
            self.assertIn("@misc{Manual2026", references)
            self.assertIn("@misc{Csv2026", references)

    def test_extract_missing_todo_treats_existing_doi_entry_as_covered(self):
        from tools import extract_bib_from_reference_csv as extractor

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lit_dir = root / "paper" / "lit"
            lit_dir.mkdir(parents=True)
            (root / "paper" / "references.bib").write_text(
                "@article{Fetched2026,\n  title={Fetched DOI paper},\n  doi={10.1234/example},\n  year={2026}\n}\n",
                encoding="utf-8",
            )
            (lit_dir / "reference.csv").write_text(
                'TRUE,"Fetched DOI paper","https://doi.org/10.1234/example",""\n',
                encoding="utf-8",
                newline="",
            )

            extractor.extract_bib_from_reference_csv(root)

            todo = (lit_dir / "missing_bibtex_todo.md").read_text(encoding="utf-8")
            self.assertIn("No selected rows are missing BibTeX", todo)

    def test_extract_missing_todo_treats_compact_existing_title_as_covered(self):
        from tools import extract_bib_from_reference_csv as extractor

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lit_dir = root / "paper" / "lit"
            lit_dir.mkdir(parents=True)
            (root / "paper" / "references.bib").write_text(
                "@inproceedings{Compact2026, title={Compact One-Line Title}, year={2026}}\n",
                encoding="utf-8",
            )
            (lit_dir / "reference.csv").write_text(
                'TRUE,"Compact One-Line Title","",""\n',
                encoding="utf-8",
                newline="",
            )

            extractor.extract_bib_from_reference_csv(root)

            todo = (lit_dir / "missing_bibtex_todo.md").read_text(encoding="utf-8")
            self.assertIn("No selected rows are missing BibTeX", todo)


class FillMissingBibtexTests(unittest.TestCase):
    def test_title_normalization_keeps_possessive_boundaries(self):
        from tools import fill_missing_bibtex as filler

        self.assertEqual(
            filler._normalize_title("Understanding Usersˇ Privacy Perceptions Towards LLMˇs RAG-based Memory"),
            filler._normalize_title("Understanding Users' Privacy Perceptions Towards LLM's RAG-based Memory"),
        )

    def test_fills_high_confidence_doi_entries_and_keeps_ambiguous_title_matches_for_review(self):
        from tools import fill_missing_bibtex as filler

        class FakeFetcher:
            def fetch_bibtex_for_doi(self, doi):
                if doi == "10.1234/example":
                    return "@article{ExistingKey,\n  title={DOI title},\n  year={2026}\n}\n"
                return None

            def fetch_bibtex_for_arxiv(self, arxiv_id):
                return None

            def query_crossref_by_title(self, title):
                return [
                    filler.CrossrefCandidate(
                        title="Similar but not exact",
                        doi="10.9999/similar",
                        score=72.0,
                        bibtex="@article{Similar2026,title={Similar but not exact},year={2026}}\n",
                    )
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lit_dir = root / "paper" / "lit"
            lit_dir.mkdir(parents=True)
            (root / "paper" / "references.bib").write_text(
                "@misc{ExistingKey,\n  title={Already present},\n  year={2025}\n}\n",
                encoding="utf-8",
            )
            (lit_dir / "reference.csv").write_text(
                "\n".join(
                    [
                        'TRUE,"DOI title","https://doi.org/10.1234/example",""',
                        'TRUE,"Only title","",""',
                    ]
                )
                + "\n",
                encoding="utf-8",
                newline="",
            )

            result = filler.fill_missing_bibtex(root, fetcher=FakeFetcher())

            self.assertEqual(result.before_count, 1)
            self.assertEqual(result.added_count, 1)
            self.assertEqual(result.unresolved_count, 1)
            self.assertEqual(result.ambiguous_count, 1)
            references = (root / "paper" / "references.bib").read_text(encoding="utf-8")
            self.assertIn("@misc{ExistingKey", references)
            self.assertIn("@article{ExistingKey-2", references)
            self.assertIn("Only title", (lit_dir / "bibtex_needs_manual_review.md").read_text(encoding="utf-8"))

    def test_fills_arxiv_doi_from_arxiv_metadata(self):
        from tools import fill_missing_bibtex as filler

        class FakeFetcher:
            def fetch_bibtex_for_doi(self, doi):
                return None

            def fetch_bibtex_for_arxiv(self, arxiv_id):
                if arxiv_id == "2604.06647":
                    return "@misc{arxiv260406647,\n  title={Feedback Adaptation},\n  year={2026}\n}\n"
                return None

            def query_crossref_by_title(self, title):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lit_dir = root / "paper" / "lit"
            lit_dir.mkdir(parents=True)
            (root / "paper" / "references.bib").write_text("", encoding="utf-8")
            (lit_dir / "reference.csv").write_text(
                'TRUE,"Feedback Adaptation","https://doi.org/10.48550/arXiv.2604.06647",""\n',
                encoding="utf-8",
                newline="",
            )

            result = filler.fill_missing_bibtex(root, fetcher=FakeFetcher())

            self.assertEqual(result.added_count, 1)
            self.assertIn("@misc{arxiv260406647", (root / "paper" / "references.bib").read_text(encoding="utf-8"))


class AuditPaperSourcesTests(unittest.TestCase):
    def test_audit_fails_when_references_bib_is_missing_or_empty(self):
        from tools import audit_paper_sources as audit

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "paper" / "lit").mkdir(parents=True)
            (root / "paper" / "source-notes").mkdir(parents=True)
            (root / "paper" / "lit" / "reference.csv").write_text("selected,title\n", encoding="utf-8")
            (root / "paper" / "source-notes" / "related-paper-notes.txt").write_text(
                "notes\n", encoding="utf-8"
            )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = audit.audit_paper_sources(root)

            self.assertNotEqual(exit_code, 0)
            self.assertIn("paper/references.bib", output.getvalue())

    def test_audit_counts_bibtex_entries_and_reports_suspicious_placeholders(self):
        from tools import audit_paper_sources as audit

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "paper" / "lit").mkdir(parents=True)
            (root / "paper" / "source-notes").mkdir(parents=True)
            (root / "paper" / "lit" / "reference.csv").write_text("selected,title\n", encoding="utf-8")
            (root / "paper" / "source-notes" / "related-paper-notes.txt").write_text(
                "A claim still has [citation needed].\n", encoding="utf-8"
            )
            (root / "paper" / "references.bib").write_text(
                textwrap.dedent(
                    """
                    @article{TODO_REPLACE_WITH_REAL_KEY,
                      title={Placeholder},
                      author={TBD},
                      year={2026}
                    }

                    @misc{FakeKey2026,
                      title={Fake looking key},
                      author={Example, A.},
                      year={2026}
                    }
                    """
                ).strip(),
                encoding="utf-8",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = audit.audit_paper_sources(root)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("BibTeX entries: 2", text)
            self.assertIn("TODO_REPLACE_WITH_REAL_KEY", text)
            self.assertIn("[citation needed]", text)
            self.assertIn("FakeKey2026", text)

    def test_audit_detects_duplicates_selected_rows_without_bibtex_and_unknown_cite_keys(self):
        from tools import audit_paper_sources as audit

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "paper" / "lit").mkdir(parents=True)
            (root / "paper" / "source-notes").mkdir(parents=True)
            (root / "paper" / "lit" / "reference.csv").write_text(
                'TRUE,"Missing row","",""\n',
                encoding="utf-8",
                newline="",
            )
            (root / "paper" / "source-notes" / "related-paper-notes.txt").write_text(
                "notes\n", encoding="utf-8"
            )
            (root / "paper" / "references.bib").write_text(
                "@misc{DupKey,title={One},year={2026}}\n\n@article{DupKey,title={Two},year={2026}}\n",
                encoding="utf-8",
            )
            (root / "paper" / "main.tex").write_text(
                r"\cite{DupKey,MissingKey}" "\n", encoding="utf-8"
            )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = audit.audit_paper_sources(root)

            self.assertNotEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("Duplicate BibTeX keys", text)
            self.assertIn("Selected references without BibTeX: 1", text)
            self.assertIn("Unknown citation keys", text)
            self.assertIn("MissingKey", text)

    def test_audit_reports_selected_rows_without_bibtex_without_failing_source_gate(self):
        from tools import audit_paper_sources as audit

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "paper" / "lit").mkdir(parents=True)
            (root / "paper" / "source-notes").mkdir(parents=True)
            (root / "paper" / "lit" / "reference.csv").write_text(
                'TRUE,"Missing row","",""\n',
                encoding="utf-8",
                newline="",
            )
            (root / "paper" / "source-notes" / "related-paper-notes.txt").write_text(
                "notes\n", encoding="utf-8"
            )
            (root / "paper" / "references.bib").write_text(
                "@misc{ValidKey,title={Valid},year={2026}}\n",
                encoding="utf-8",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = audit.audit_paper_sources(root)

            self.assertEqual(exit_code, 0)
            self.assertIn("Selected references without BibTeX: 1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
