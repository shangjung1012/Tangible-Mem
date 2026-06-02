from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable


TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", re.IGNORECASE)
SLUG_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)
PHRASE_SEP_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)


def normalize_ascii_token(token: str) -> str:
    clean = token.lower()
    if (
        len(clean) > 4
        and clean.endswith("s")
        and not clean.endswith(("ss", "us", "is"))
    ):
        return clean[:-1]
    return clean


def normalize_phrase(text: str) -> str:
    parts = PHRASE_SEP_RE.sub(" ", text or "").lower().split()
    normalized = [normalize_ascii_token(part) if re.fullmatch(r"[a-z0-9]+", part) else part for part in parts]
    return " ".join(normalized)

def tokens(text: str, *, stopwords: set[str] | None = None, max_cjk_token_chars: int = 12) -> list[str]:
    stopword_set = stopwords or set()
    output: list[str] = []
    for token in TOKEN_RE.findall(text or ""):
        clean = normalize_ascii_token(token)
        if len(clean) < 2 or clean in stopword_set or clean.isdigit():
            continue
        if re.fullmatch(r"[a-z]{1,3}\d{3,4}", clean):
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", clean) and len(clean) > max_cjk_token_chars:
            continue
        output.append(clean)
    return output


def token_sequences(
    text: str,
    *,
    stopwords: set[str] | None = None,
    max_cjk_token_chars: int = 12,
) -> list[list[str]]:
    """Return token runs without crossing removed stopword/filler boundaries."""
    stopword_set = stopwords or set()
    sequences: list[list[str]] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if current:
            sequences.append(current)
            current = []

    last_end = 0
    for match in TOKEN_RE.finditer(text or ""):
        gap = (text or "")[last_end : match.start()]
        if any(char in gap for char in ".。!?！？;；\n\r"):
            flush()
        clean = normalize_ascii_token(match.group(0))
        if (
            len(clean) < 2
            or clean in stopword_set
            or clean.isdigit()
            or re.fullmatch(r"[a-z]{1,3}\d{3,4}", clean)
            or (re.fullmatch(r"[\u4e00-\u9fff]+", clean) and len(clean) > max_cjk_token_chars)
        ):
            flush()
            continue
        current.append(clean)
        last_end = match.end()
    flush()
    return sequences


def slugify(text: str) -> str:
    slug = SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return slug or "topic"


def ngrams(
    token_list: list[str],
    *,
    min_n: int = 1,
    max_n: int = 3,
    generic_terms: set[str] | None = None,
) -> list[str]:
    generic_set = generic_terms or set()
    grams: list[str] = []
    for size in range(min_n, max_n + 1):
        for index in range(0, max(0, len(token_list) - size + 1)):
            chunk = token_list[index : index + size]
            if not chunk:
                continue
            if generic_set and all(term in generic_set for term in chunk):
                continue
            grams.append(" ".join(chunk))
    return grams


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    left = set(a)
    right = set(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def cosine_counter(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    shared = set(a) & set(b)
    dot = sum(a[key] * b[key] for key in shared)
    left = math.sqrt(sum(value * value for value in a.values()))
    right = math.sqrt(sum(value * value for value in b.values()))
    if not left or not right:
        return 0.0
    return dot / (left * right)
