from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
sys.path.insert(0, str(LONG_TERM_DIR))

from gemini_clients import create_gemini_client, normalize_api_keys  # noqa: E402
from io_utils import parse_gemini_api_keys_from_env  # noqa: E402


class _FakeModels:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def generate_content(self, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
        return self.api_key

    def embed_content(self, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
        return self.api_key


class _FakeClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.models = _FakeModels(api_key)


class GeminiApiKeyTests(unittest.TestCase):
    def test_parse_gemini_api_keys_from_env(self) -> None:
        keys = parse_gemini_api_keys_from_env(
            {
                "GEMINI_API_KEYS": "key_a, key_b",
                "GEMINI_API_KEY": "key_single",
                "GEMINI_API_KEY_2": "key_b",
                "GEMINI_API_KEY_3": "key_c",
            }
        )

        self.assertEqual(keys, ["key_a", "key_b"])

    def test_parse_numbered_keys_from_env(self) -> None:
        keys = parse_gemini_api_keys_from_env(
            {
                "GEMINI_API_KEY": "key_single",
                "GEMINI_API_KEY_1": "key_a",
                "GEMINI_API_KEY_2": "key_b",
                "GEMINI_API_KEY_3": "key_c",
            }
        )

        self.assertEqual(keys, ["key_a", "key_b", "key_c"])

    def test_parse_legacy_numbered_keys_without_underscore(self) -> None:
        keys = parse_gemini_api_keys_from_env(
            {
                "GEMINI_API_KEY1": "key_a",
                "GEMINI_API_KEY2": "key_b",
                "GEMINI_API_KEY3": "key_c",
            }
        )

        self.assertEqual(keys, ["key_a", "key_b", "key_c"])

    def test_normalize_api_keys_deduplicates(self) -> None:
        self.assertEqual(
            normalize_api_keys("key_a, key_b; key_a"),
            ["key_a", "key_b"],
        )

    def test_round_robin_client_rotates_model_calls(self) -> None:
        with patch("gemini_clients.genai.Client", _FakeClient):
            client = create_gemini_client(["key_a", "key_b", "key_c"])
            observed = [
                client.models.generate_content(model="gemini-2.5-flash")
                for _ in range(5)
            ]
            observed.append(client.models.embed_content(model="models/embedding"))

        self.assertEqual(
            observed,
            ["key_a", "key_b", "key_c", "key_a", "key_b", "key_c"],
        )

    def test_round_robin_client_reuses_pool_for_same_key_set(self) -> None:
        keys = ["pool_key_a", "pool_key_b", "pool_key_c"]
        with patch("gemini_clients.genai.Client", _FakeClient):
            first_client = create_gemini_client(keys)
            self.assertEqual(first_client.models.generate_content(), "pool_key_a")
            self.assertEqual(first_client.models.generate_content(), "pool_key_b")

            second_client = create_gemini_client(keys)
            self.assertIs(second_client, first_client)
            self.assertEqual(second_client.models.generate_content(), "pool_key_c")


if __name__ == "__main__":
    unittest.main()
