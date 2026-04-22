"""Small helpers for Gemini clients, including API-key round-robin."""

from __future__ import annotations

from collections.abc import Sequence
from threading import Lock
from typing import Any

from google import genai

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

    def __init__(self, api_keys: Sequence[str]) -> None:
        keys = normalize_api_keys(api_keys)
        self._clients = [genai.Client(api_key=key) for key in keys]
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


def create_gemini_client(api_key_or_keys: str | Sequence[str]) -> Any:
    keys = normalize_api_keys(api_key_or_keys)
    cache_key = tuple(keys)
    with _CLIENT_CACHE_LOCK:
        cached = _CLIENT_CACHE.get(cache_key)
        if cached is not None:
            return cached
        if len(keys) == 1:
            client = genai.Client(api_key=keys[0])
        else:
            client = RoundRobinGeminiClient(keys)
        _CLIENT_CACHE[cache_key] = client
        return client
