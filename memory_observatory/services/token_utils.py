from __future__ import annotations

import re
from typing import Any

ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_'-]+")


def estimate_tokens(text: str) -> int:
    """Deterministic rough token estimate for mixed CJK / ASCII context."""
    value = str(text or "")
    if not value:
        return 0
    cjk_count = sum(1 for char in value if "\u4e00" <= char <= "\u9fff")
    ascii_text = "".join(char if ord(char) < 128 else " " for char in value)
    ascii_words = ASCII_WORD_RE.findall(ascii_text)
    ascii_chars = sum(len(word) for word in ascii_words)
    punctuation = max(0, len(value) - cjk_count - ascii_chars)
    estimate = cjk_count + max(1, ascii_chars // 4) + max(0, punctuation // 12)
    return max(1, int(estimate))


def usage_metadata_to_tokens(response: Any) -> dict[str, int | None]:
    """Extract Gemini usage metadata when the SDK response exposes it."""
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None and isinstance(response, dict):
        metadata = response.get("usage_metadata")
    if metadata is None:
        return {
            "actual_input_tokens": None,
            "actual_output_tokens": None,
            "actual_total_tokens": None,
        }

    def read(*names: str) -> int | None:
        for name in names:
            if isinstance(metadata, dict) and metadata.get(name) is not None:
                return int(metadata[name])
            value = getattr(metadata, name, None)
            if value is not None:
                return int(value)
        return None

    input_tokens = read("prompt_token_count", "input_token_count")
    output_tokens = read("candidates_token_count", "output_token_count")
    total_tokens = read("total_token_count")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "actual_input_tokens": input_tokens,
        "actual_output_tokens": output_tokens,
        "actual_total_tokens": total_tokens,
    }


def context_token_metrics(context: str) -> dict[str, int | str | None]:
    return {
        "context_char_count": len(str(context or "")),
        "estimated_context_tokens": estimate_tokens(context),
        "actual_input_tokens": None,
        "actual_output_tokens": None,
        "actual_total_tokens": None,
        "token_source": "estimated",
    }

