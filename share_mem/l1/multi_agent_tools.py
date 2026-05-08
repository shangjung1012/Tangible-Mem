"""Local helper functions for the explicit multi-agent L1 pipeline."""

from __future__ import annotations

import json
import re
from typing import Any

from .multi_agent_state import TranscriptLine

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")


def extract_json_object(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        raise RuntimeError("Model returned an empty response.")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        raise RuntimeError("Response does not contain a JSON object.")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise RuntimeError("JSON response must be an object.")
    return data


def tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in TOKEN_RE.findall(str(text or "")):
        clean = token.lower().strip()
        if clean:
            tokens.add(clean)
        if re.fullmatch(r"[\u4e00-\u9fff]+", clean) and len(clean) > 1:
            tokens.update(clean)
    return tokens


def jaccard(left: str, right: str) -> float:
    left_tokens = tokenize(left)
    right_tokens = tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def token_coverage(needle: str, haystack: str) -> float:
    needle_tokens = tokenize(needle)
    haystack_tokens = tokenize(haystack)
    if not needle_tokens or not haystack_tokens:
        return 0.0
    return len(needle_tokens & haystack_tokens) / len(needle_tokens)


def local_alignment_score(content: str, evidence_text: str) -> tuple[float, dict[str, float]]:
    content_clean = str(content or "").strip().lower()
    evidence_clean = str(evidence_text or "").strip().lower()
    lexical_jaccard = jaccard(content_clean, evidence_clean)
    content_coverage = token_coverage(content_clean, evidence_clean)
    evidence_coverage = token_coverage(evidence_clean, content_clean)
    span_inclusion = 0.0
    if content_clean and evidence_clean:
        if content_clean in evidence_clean or evidence_clean in content_clean:
            span_inclusion = 1.0
    score = max(
        lexical_jaccard,
        content_coverage * 0.85,
        evidence_coverage * 0.55,
        span_inclusion,
    )
    signals = {
        "lexical_jaccard": round(lexical_jaccard, 3),
        "content_token_coverage": round(content_coverage, 3),
        "evidence_token_coverage": round(evidence_coverage, 3),
        "span_inclusion": round(span_inclusion, 3),
    }
    return round(score, 3), signals


def clamp_float(value: Any, fallback: float = 0.5) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = fallback
    return max(0.0, min(1.0, score))


def unique_strings(values: Any) -> list[str]:
    output: list[str] = []
    if not isinstance(values, list):
        return output
    for value in values:
        clean = str(value).strip()
        if clean and clean not in output:
            output.append(clean)
    return output


def format_lines(lines: list[TranscriptLine]) -> str:
    return "\n".join(f"{line.line_id}: {line.text}" for line in lines)


def lines_by_id(lines: list[TranscriptLine]) -> dict[int, TranscriptLine]:
    return {line.line_id: line for line in lines}


def slice_lines(lines: list[TranscriptLine], start_line: int, end_line: int) -> list[TranscriptLine]:
    return [
        line
        for line in lines
        if int(start_line) <= line.line_id <= int(end_line)
    ]


def evidence_quote(lines: list[TranscriptLine], line_ids: list[int], *, max_chars: int = 360) -> str:
    by_id = lines_by_id(lines)
    chunks = [by_id[line_id].text for line_id in line_ids if line_id in by_id]
    text = " ".join(chunks).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."
