import json
import re
import struct
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
INDEX = SITE / "index.html"
README = ROOT / "README.md"
PUBLIC_SITE_URL = "https://shangjung1012.github.io/Tangible-Mem/"
REPOSITORY_URL = "https://github.com/shangjung1012/Tangible-Mem"
INTERNAL_RESULTS = (
    ROOT
    / "memory_observatory"
    / "runs"
    / "experiment_final"
    / "observatory_score_summary.json"
)
ICSI_RESULTS = (
    ROOT
    / "optimization"
    / "reports"
    / "icsi_bmr_full_completed29_system_comparison_revised_20260614"
    / "system_comparison_summary.json"
)


class ProjectPageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.local_references = []
        self.images = []
        self.links = []
        self.meta = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if element_id := attributes.get("id"):
            self.ids.add(element_id)

        for attribute in ("href", "src", "data"):
            if value := attributes.get(attribute):
                self.local_references.append((tag, attribute, value))

        if tag == "img":
            self.images.append(attributes)
        elif tag == "a":
            self.links.append(attributes)
        elif tag == "meta":
            self.meta.append(attributes)
        elif tag == "script":
            self.scripts.append(attributes)


class TangibleMemPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text(encoding="utf-8")
        cls.readme = README.read_text(encoding="utf-8")
        cls.parser = ProjectPageParser()
        cls.parser.feed(cls.html)

    def test_local_assets_exist(self):
        missing = []
        for tag, attribute, reference in self.parser.local_references:
            parsed = urlsplit(reference)
            if parsed.scheme or parsed.netloc or reference.startswith(("#", "mailto:")):
                continue
            path = unquote(parsed.path)
            if not path:
                continue
            target = SITE / path.lstrip("/")
            if not target.exists():
                missing.append(f"{tag}[{attribute}]={reference}")
        self.assertEqual([], missing, f"Missing local resources: {missing}")

    def test_local_assets_are_subpath_safe(self):
        unsafe = []
        for tag, attribute, reference in self.parser.local_references:
            parsed = urlsplit(reference)
            if parsed.scheme or parsed.netloc or reference.startswith(("#", "mailto:")):
                continue
            if parsed.path.startswith("/"):
                unsafe.append(f"{tag}[{attribute}]={reference}")
        self.assertEqual([], unsafe, f"Root-relative resources are not subpath-safe: {unsafe}")

    def test_stylesheet_assets_exist(self):
        stylesheet = SITE / "static" / "css" / "index.css"
        css = stylesheet.read_text(encoding="utf-8")
        references = re.findall(r"url\([\"']?([^\"')]+)", css)
        missing = []
        for reference in references:
            parsed = urlsplit(reference)
            if parsed.scheme or parsed.netloc or reference.startswith("data:"):
                continue
            target = (stylesheet.parent / unquote(parsed.path)).resolve()
            if not target.exists():
                missing.append(reference)
        self.assertEqual([], missing, f"Missing CSS resources: {missing}")

    def test_readme_local_links_and_images_exist(self):
        references = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", self.readme)
        missing = []
        for reference in references:
            parsed = urlsplit(reference)
            if parsed.scheme or parsed.netloc or reference.startswith(("#", "mailto:")):
                continue
            target = ROOT / unquote(parsed.path)
            if not target.exists():
                missing.append(reference)
        self.assertEqual([], missing, f"Missing README resources: {missing}")

    def test_required_sections_and_metadata_exist(self):
        expected_ids = {
            "main-content",
            "top",
            "abstract",
            "system",
            "observatory",
            "evaluation",
            "resources",
        }
        self.assertTrue(expected_ids.issubset(self.parser.ids))
        self.assertIn(
            f'<link rel="canonical" href="{PUBLIC_SITE_URL}" />',
            self.html,
        )
        self.assertIn('property="og:image"', self.html)
        self.assertIn('name="twitter:card" content="summary_large_image"', self.html)
        self.assertIn('"@type": "SoftwareSourceCode"', self.html)
        self.assertIn(f'property="og:url" content="{PUBLIC_SITE_URL}"', self.html)
        self.assertIn(
            f'content="{PUBLIC_SITE_URL}static/images/social-preview.png"',
            self.html,
        )
        self.assertIn(f'"url": "{PUBLIC_SITE_URL}"', self.html)
        self.assertIn(f'"codeRepository": "{REPOSITORY_URL}"', self.html)
        self.assertNotIn('name="citation_', self.html.lower())

    def test_public_urls_use_current_repository_name(self):
        public_content = f"{self.readme}\n{self.html}"
        self.assertIn(PUBLIC_SITE_URL, self.readme)
        self.assertIn(REPOSITORY_URL, self.readme)
        self.assertIn(PUBLIC_SITE_URL, self.html)
        self.assertIn(REPOSITORY_URL, self.html)
        self.assertNotIn("github.com/shangjung1012/virtual-mentor", public_content)
        self.assertNotIn("shangjung1012.github.io/virtual-mentor", public_content)
        self.assertNotIn("Virtual Mentor", public_content)

    def test_social_preview_is_1200_by_630(self):
        preview = SITE / "static" / "images" / "social-preview.png"
        with preview.open("rb") as image_file:
            header = image_file.read(24)
        self.assertEqual(b"\x89PNG\r\n\x1a\n", header[:8])
        self.assertEqual((1200, 630), struct.unpack(">II", header[16:24]))

    def test_page_has_no_template_placeholders(self):
        forbidden = (
            "TODO",
            "PAPER_TITLE",
            "YOUR_NAME",
            "sample.pdf",
            "lorem ipsum",
            "arxiv",
            "bibtex",
            "conference name",
        )
        lowered = f"{self.html}\n{self.readme}".lower()
        found = [term for term in forbidden if term.lower() in lowered]
        self.assertEqual([], found, f"Placeholder content remains: {found}")

    def test_images_have_alternative_text(self):
        self.assertGreaterEqual(len(self.parser.images), 6)
        missing = [image.get("src", "<unknown>") for image in self.parser.images if not image.get("alt", "").strip()]
        self.assertEqual([], missing, f"Images without alt text: {missing}")

    def test_new_window_links_are_safe(self):
        unsafe = [
            link.get("href", "<unknown>")
            for link in self.parser.links
            if link.get("target") == "_blank"
            and not {"noopener", "noreferrer"}.issubset(set(link.get("rel", "").split()))
        ]
        self.assertEqual([], unsafe, f"Unsafe target=_blank links: {unsafe}")

    def test_template_attribution_is_present(self):
        self.assertIn("Academic Project Page Template", self.html)
        self.assertIn("https://github.com/eliahuhorwitz/Academic-project-page-template", self.html)
        self.assertIn("CC BY-SA 4.0", self.html)
        self.assertTrue((SITE / "NOTICE.txt").is_file())

    def test_pages_workflow_tests_and_uploads_only_site(self):
        workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(
            encoding="utf-8"
        )
        required = (
            "actions/checkout@v4",
            "actions/setup-python@v5",
            "python -m unittest tests.test_project_page",
            "actions/configure-pages@v5",
            "actions/upload-pages-artifact@v3",
            "path: site",
            "actions/deploy-pages@v5",
            "workflow_dispatch:",
        )
        for item in required:
            self.assertIn(item, workflow)

    def test_internal_evaluation_matches_saved_results(self):
        results = json.loads(INTERNAL_RESULTS.read_text(encoding="utf-8"))
        labels = {
            "layered_memory": "Layered Memory",
            "rag_baseline": "RAG Baseline",
            "full_context": "Full Context",
        }
        for document in (self.html, self.readme):
            for key, label in labels.items():
                score = results["score_summary"][key]["final_quality_score"]
                tokens = round(results["run_summary_metrics"]["avg_total_tokens"][key])
                pattern = rf"{label}.*?{score:.3f}.*?{tokens:,}"
                self.assertRegex(document, re.compile(pattern, re.DOTALL))
        self.assertEqual(14, results["run_summary_metrics"]["query_count"])
        self.assertIn("14 questions", self.html)
        self.assertIn("Fourteen internal", self.readme)

    def test_icsi_diagnostic_matches_saved_results(self):
        results = json.loads(ICSI_RESULTS.read_text(encoding="utf-8"))["summary"]
        labels = {
            "optimization_v2_layered": "Layered Memory",
            "rag_l1_lexical": "Lexical RAG",
            "full_context_l1": "Full Context L1",
        }
        for document in (self.html, self.readme):
            for key, label in labels.items():
                recall = results["expected_l1_recall"][key]
                tokens = round(results["avg_context_tokens"][key])
                recall_text = "1.0000" if recall == 1 else f"{recall:.4f}"
                pattern = rf"{label}.*?{recall_text}.*?{tokens:,}"
                self.assertRegex(document, re.compile(pattern, re.DOTALL))
        self.assertEqual(20, results["query_count"])
        self.assertIn("20 held-out questions", self.html)
        self.assertIn("Twenty held-out ICSI questions", self.readme)
        self.assertRegex(
            self.html,
            re.compile(
                r"No answer generation or\s+answer-quality judging was used",
                re.DOTALL,
            ),
        )


if __name__ == "__main__":
    unittest.main()
