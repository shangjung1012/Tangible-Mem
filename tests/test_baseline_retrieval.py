from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import baseline_retrieval  # noqa: E402


class BaselineRetrievalTests(unittest.TestCase):
    def test_parse_meeting_ids_deduplicates_csv_values(self) -> None:
        self.assertEqual(
            baseline_retrieval.parse_meeting_ids("0307, 0318;0307 0506"),
            ["0307", "0318", "0506"],
        )

    def test_lexical_rag_retrieves_raw_transcript_chunks_without_l2_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0307.txt").write_text(
                "We discussed memory retrieval and baseline comparison.",
                encoding="utf-8",
            )
            (root / "0318.txt").write_text(
                "This meeting only discussed unrelated room logistics.",
                encoding="utf-8",
            )

            context = baseline_retrieval.retrieve_lexical_rag_context(
                "memory retrieval baseline",
                transcript_dir=root,
                top_k=1,
            )

        self.assertIn("=== Lexical RAG Transcript Baseline ===", context)
        self.assertIn("[0307#chunk-1]", context)
        self.assertIn("memory retrieval", context)
        self.assertNotIn("L2 主題脈絡", context)

    def test_embedding_rag_uses_embeddings_and_raw_transcript_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0307.txt").write_text(
                "memory retrieval baseline comparison",
                encoding="utf-8",
            )
            (root / "0318.txt").write_text(
                "unrelated room logistics",
                encoding="utf-8",
            )
            cache_path = root / "cache.json"

            calls: list[str] = []

            def fake_embed_text(text, api_key, cache):
                del api_key, cache
                calls.append(text)
                lower = str(text).lower()
                if "memory retrieval" in lower:
                    return [1.0, 0.0]
                return [0.0, 1.0]

            with patch.object(
                baseline_retrieval,
                "embed_text",
                side_effect=fake_embed_text,
            ):
                context = baseline_retrieval.retrieve_plain_rag_context(
                    "memory retrieval",
                    api_key="fake-key",
                    transcript_dir=root,
                    top_k=1,
                    cache_path=cache_path,
                )

        self.assertIn("=== Embedding RAG Transcript Baseline ===", context)
        self.assertIn("[0307#chunk-1]", context)
        self.assertNotIn("L2 主題脈絡", context)
        self.assertGreaterEqual(len(calls), 2)

    def test_full_transcript_uses_gold_meeting_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0307.txt").write_text("0307 transcript", encoding="utf-8")
            (root / "0506.txt").write_text("0506 transcript", encoding="utf-8")

            context = baseline_retrieval.retrieve_full_transcript_context(
                "0506, 0307",
                transcript_dir=root,
            )

        self.assertIn("--- meeting 0506 ---", context)
        self.assertIn("0506 transcript", context)
        self.assertIn("--- meeting 0307 ---", context)
        self.assertIn("0307 transcript", context)

    def test_full_transcript_does_not_truncate_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0506.txt").write_text("x" * 1200, encoding="utf-8")

            context = baseline_retrieval.retrieve_full_transcript_context(
                "0506",
                transcript_dir=root,
            )
            limited = baseline_retrieval.retrieve_full_transcript_context(
                "0506",
                transcript_dir=root,
                max_context_chars=100,
            )

        self.assertGreater(len(context), 1200)
        self.assertNotIn("...(truncated)", context)
        self.assertIn("...(truncated)", limited)


if __name__ == "__main__":
    unittest.main()
