"""Embedding helpers with persistent JSON cache."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import time
from pathlib import Path

from gemini_clients import create_gemini_client
from schema import EMBED_MODEL_NAME

DEFAULT_CACHE_PATH = Path(__file__).parent / ".embedding_cache.json"
FALLBACK_EMBED_MODELS = ("models/gemini-embedding-001",)


def _normalize_model_name(model: str) -> str:
    model = model.strip()
    if not model:
        return model
    if model.startswith("models/"):
        return model
    return f"models/{model}"


def _text_key(text: str, model: str = "") -> str:
    # Include model name to avoid mixing vectors from different embedding models.
    key_source = f"{model}\n{text}" if model else text
    return hashlib.sha256(key_source.encode("utf-8")).hexdigest()[:16]


def _is_retryable_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {429, 500, 502, 503, 504}:
        return True
    msg = str(exc).upper()
    retry_tokens = (
        "429",
        "500",
        "502",
        "503",
        "504",
        "RESOURCE_EXHAUSTED",
        "UNAVAILABLE",
        "RATE LIMIT",
    )
    return any(token in msg for token in retry_tokens)


def _is_not_found_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 404:
        return True
    return "NOT_FOUND" in str(exc).upper()


class EmbedCache:
    """Persistent embedding cache backed by a JSON file."""

    def __init__(self, path: Path = DEFAULT_CACHE_PATH) -> None:
        self.path = path
        self._data: dict[str, list[float]] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._data = {}
            return
        if isinstance(data, dict):
            self._data = data

    def save(self) -> None:
        """Flush cache to disk only when new values were added."""
        if not self._dirty:
            return
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False),
            encoding="utf-8",
        )
        self._dirty = False

    def get(self, text: str, model: str = "") -> list[float] | None:
        return self._data.get(_text_key(text, model=model))

    def set(self, text: str, embedding: list[float], model: str = "") -> None:
        self._data[_text_key(text, model=model)] = embedding
        self._dirty = True


def embed_text(
    text: str,
    api_key: str | list[str],
    cache: EmbedCache,
    model: str = EMBED_MODEL_NAME,
    max_retries: int = 6,
) -> list[float]:
    """Return embedding for *text*, with cache + retry + model fallback."""
    env_model = os.getenv("GEMINI_EMBED_MODEL", "").strip()
    preferred_model = _normalize_model_name(env_model or model)

    model_candidates: list[str] = [preferred_model]
    for fallback_model in FALLBACK_EMBED_MODELS:
        normalized = _normalize_model_name(fallback_model)
        if normalized and normalized not in model_candidates:
            model_candidates.append(normalized)

    client = create_gemini_client(api_key)
    last_exc: Exception | None = None

    for candidate_model in model_candidates:
        cached = cache.get(text, model=candidate_model)
        if cached is not None:
            return cached

        for attempt in range(1, max_retries + 1):
            try:
                result = client.models.embed_content(model=candidate_model, contents=text)
                emb: list[float] = result.embeddings[0].values  # type: ignore[index]
                cache.set(text, emb, model=candidate_model)
                return emb
            except Exception as exc:
                last_exc = exc

                # Move to next model if this model is unavailable for current API/user.
                if _is_not_found_error(exc):
                    break

                if attempt >= max_retries or not _is_retryable_error(exc):
                    raise

                backoff = min(90.0, 2.0 * (2 ** (attempt - 1)))
                wait_s = backoff + random.uniform(0.0, 1.5)
                time.sleep(wait_s)

    if last_exc:
        raise RuntimeError(
            "Embedding model unavailable. Try setting GEMINI_EMBED_MODEL, "
            "for example 'models/gemini-embedding-001'."
        ) from last_exc
    raise RuntimeError("Embedding failed unexpectedly without an exception.")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
