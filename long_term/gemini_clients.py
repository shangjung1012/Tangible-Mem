"""Small helpers for Gemini clients, including API-key round-robin."""

from __future__ import annotations

import os
from collections.abc import Sequence
from threading import Lock
from typing import Any

from google import genai
from io_utils import ensure_env_loaded, is_vertex_ai_enabled, parse_gemini_api_keys_from_env

_CLIENT_CACHE: dict[tuple[str, ...], Any] = {}
_CLIENT_CACHE_LOCK = Lock()


def normalize_api_keys(api_key_or_keys: str | Sequence[str]) -> list[str]:
    if isinstance(api_key_or_keys, str):
        pieces = api_key_or_keys.replace(";", ",").split(",")
        keys = [piece.strip() for piece in pieces if piece.strip()]
    else:
        keys = [str(key).strip() for key in api_key_or_keys if str(key).strip()]

    unique: list[str] = []
    for key in keys:
        if key not in unique:
            unique.append(key)
    if not unique:
        raise RuntimeError("At least one Gemini API key is required.")
    return unique


def _normalize_optional_api_keys(
    api_key_or_keys: str | Sequence[str] | None,
) -> list[str]:
    if api_key_or_keys is None:
        return []
    if isinstance(api_key_or_keys, str):
        if not api_key_or_keys.strip():
            return []
    elif not any(str(key).strip() for key in api_key_or_keys):
        return []
    return normalize_api_keys(api_key_or_keys)


def _resolve_api_keys(api_key_or_keys: str | Sequence[str] | None) -> list[str]:
    ensure_env_loaded()
    explicit_keys = _normalize_optional_api_keys(api_key_or_keys)
    if explicit_keys:
        return explicit_keys
    return parse_gemini_api_keys_from_env()


def get_configured_client_count(api_key_or_keys: str | Sequence[str] | None = None) -> int:
    keys = _resolve_api_keys(api_key_or_keys)
    if keys:
        use_vertex = is_vertex_ai_enabled()
        project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if use_vertex and (project or credentials_path):
            return 1
        return len(keys)
    return 1 if is_vertex_ai_enabled() else 0


class _RoundRobinModels:
    def __init__(self, pool: "RoundRobinGeminiClient") -> None:
        self._pool = pool

    def __getattr__(self, method_name: str) -> Any:
        def _call(*args: Any, **kwargs: Any) -> Any:
            client = self._pool.next_client()
            return getattr(client.models, method_name)(*args, **kwargs)

        return _call


class RoundRobinGeminiClient:
    """Minimal GenAI client facade that rotates keys once per model call."""

    def __init__(self, client_kwargs_pool: Sequence[dict[str, Any]]) -> None:
        if not client_kwargs_pool:
            raise RuntimeError("At least one GenAI client configuration is required.")
        self._clients = [genai.Client(**kwargs) for kwargs in client_kwargs_pool]
        self._index = 0
        self._lock = Lock()
        self.models = _RoundRobinModels(self)

    @property
    def key_count(self) -> int:
        return len(self._clients)

    def next_client(self) -> genai.Client:
        with self._lock:
            client = self._clients[self._index]
            self._index = (self._index + 1) % len(self._clients)
            return client


def create_gemini_client(api_key_or_keys: str | Sequence[str] | None = None) -> Any:
    ensure_env_loaded()
    keys = _resolve_api_keys(api_key_or_keys)
    use_vertex = is_vertex_ai_enabled()
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "").strip()
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

    if use_vertex:
        if project or credentials_path:
            client_kwargs = {"vertexai": True}
            if project:
                client_kwargs["project"] = project
            if location:
                client_kwargs["location"] = location
            cache_key = (
                "vertex",
                "project",
                project,
                location,
                credentials_path,
            )
            client_kwargs_pool = [client_kwargs]
        elif keys:
            cache_key = ("vertex", "api_key", *keys)
            client_kwargs_pool = [
                {"vertexai": True, "api_key": key}
                for key in keys
            ]
        else:
            client_kwargs = {"vertexai": True}
            if location:
                client_kwargs["location"] = location
            cache_key = ("vertex", "auto", project, location, credentials_path)
            client_kwargs_pool = [client_kwargs]
    else:
        if not keys:
            raise RuntimeError(
                "Gemini API key is missing. Set GEMINI_API_KEY / GEMINI_API_KEYS, "
                "or enable Vertex AI with GOOGLE_GENAI_USE_VERTEXAI=true."
            )
        cache_key = ("gemini", *keys)
        client_kwargs_pool = [{"api_key": key} for key in keys]

    with _CLIENT_CACHE_LOCK:
        cached = _CLIENT_CACHE.get(cache_key)
        if cached is not None:
            return cached
        if len(client_kwargs_pool) == 1:
            client = genai.Client(**client_kwargs_pool[0])
        else:
            client = RoundRobinGeminiClient(client_kwargs_pool)
        _CLIENT_CACHE[cache_key] = client
        return client
