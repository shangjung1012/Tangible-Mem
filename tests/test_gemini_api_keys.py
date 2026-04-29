from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
sys.path.insert(0, str(LONG_TERM_DIR))

import gemini_clients  # noqa: E402
from gemini_clients import create_gemini_client, get_configured_client_count, normalize_api_keys  # noqa: E402
from io_utils import is_vertex_ai_enabled, parse_gemini_api_keys_from_env  # noqa: E402


class _FakeModels:
    def __init__(self, client: "_FakeClient") -> None:
        self.client = client

    def generate_content(self, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
        return self.client.api_key or ("vertex" if self.client.vertexai else "missing")

    def embed_content(self, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
        return self.client.api_key or ("vertex" if self.client.vertexai else "missing")


class _FakeClient:
    def __init__(self, api_key: str | None = None, vertexai: bool | None = None, project: str | None = None, location: str | None = None) -> None:
        self.api_key = api_key
        self.vertexai = bool(vertexai)
        self.project = project
        self.location = location
        self.models = _FakeModels(self)


class GeminiApiKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        gemini_clients._CLIENT_CACHE.clear()

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

    def test_parse_google_api_key_from_env(self) -> None:
        keys = parse_gemini_api_keys_from_env(
            {
                "GOOGLE_API_KEY": "vertex_key",
                "GEMINI_API_KEY": "gemini_key",
            }
        )

        self.assertEqual(keys, ["vertex_key"])

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
        with (
            patch("gemini_clients.ensure_env_loaded"),
            patch.dict(os.environ, {}, clear=True),
            patch("gemini_clients.genai.Client", _FakeClient),
        ):
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

    def test_create_vertex_client_uses_project_config_without_api_key(self) -> None:
        with (
            patch("gemini_clients.ensure_env_loaded"),
            patch("gemini_clients.genai.Client", _FakeClient),
            patch.dict(
                os.environ,
                {
                    "GOOGLE_GENAI_USE_VERTEXAI": "true",
                    "GOOGLE_CLOUD_PROJECT": "demo-project",
                    "GOOGLE_CLOUD_LOCATION": "global",
                },
                clear=True,
            ),
        ):
            client = create_gemini_client([])

        self.assertTrue(client.vertexai)
        self.assertEqual(client.project, "demo-project")
        self.assertEqual(client.location, "global")
        self.assertIsNone(client.api_key)

    def test_vertex_project_mode_reports_single_client_slot(self) -> None:
        with (
            patch("gemini_clients.ensure_env_loaded"),
            patch.dict(
                os.environ,
                {
                    "GOOGLE_GENAI_USE_VERTEXAI": "true",
                    "GOOGLE_CLOUD_PROJECT": "demo-project",
                    "GOOGLE_CLOUD_LOCATION": "global",
                    "GOOGLE_API_KEY": "vertex_key_a",
                },
                clear=True,
            ),
        ):
            self.assertTrue(is_vertex_ai_enabled())
            self.assertEqual(get_configured_client_count([]), 1)

    def test_round_robin_client_reuses_pool_for_same_key_set(self) -> None:
        keys = ["pool_key_a", "pool_key_b", "pool_key_c"]
        with (
            patch("gemini_clients.ensure_env_loaded"),
            patch.dict(os.environ, {}, clear=True),
            patch("gemini_clients.genai.Client", _FakeClient),
        ):
            first_client = create_gemini_client(keys)
            self.assertEqual(first_client.models.generate_content(), "pool_key_a")
            self.assertEqual(first_client.models.generate_content(), "pool_key_b")

            second_client = create_gemini_client(keys)
            self.assertIs(second_client, first_client)
            self.assertEqual(second_client.models.generate_content(), "pool_key_c")


if __name__ == "__main__":
    unittest.main()
