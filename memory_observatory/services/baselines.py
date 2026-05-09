from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Sequence

from .data_loader import ObservatoryDataLoader
from .token_utils import context_token_metrics

TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [item.lower() for item in TOKEN_RE.findall(str(text or "").lower())]


def _parse_meeting_ids(value: str | Sequence[str]) -> list[str]:
    if isinstance(value, str):
        raw = re.split(r"[\s,;]+", value)
    else:
        raw = [str(item) for item in value]
    output: list[str] = []
    for item in raw:
        clean = item.strip()
        if clean and clean not in output:
            output.append(clean)
    return output


def _transcript_lines(text: str) -> list[str]:
    return [line for line in str(text or "").splitlines() if line.strip()]


def _line_chunks(lines: list[str], *, chunk_size_lines: int, overlap_lines: int) -> list[tuple[int, int, str]]:
    chunk_size_lines = max(1, int(chunk_size_lines))
    overlap_lines = max(0, min(int(overlap_lines), chunk_size_lines - 1))
    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(lines):
        end = min(len(lines), start + chunk_size_lines)
        chunks.append((start + 1, end, "\n".join(lines[start:end])))
        if end >= len(lines):
            break
        start = max(start + 1, end - overlap_lines)
    return chunks


def build_full_context(
    *,
    repo_root: Path | str,
    meeting_ids: str | Sequence[str] = "",
    scope: str = "all",
    max_context_chars: int = 0,
    source: str = "transcripts",
) -> dict[str, Any]:
    started = time.perf_counter()
    loader = ObservatoryDataLoader(repo_root)
    transcripts = loader.load_transcripts()
    ids = sorted(transcripts) if scope == "all" else _parse_meeting_ids(meeting_ids)
    parts = ["=== Full Context Baseline ==="]
    included: list[str] = []
    for meeting_id in ids:
        transcript = transcripts.get(meeting_id)
        if not transcript:
            continue
        included.append(meeting_id)
        parts.append(f"\n--- meeting {meeting_id} ---")
        parts.append(transcript.strip())
    context = "\n".join(parts)
    original_chars = len(context)
    truncated = bool(max_context_chars and max_context_chars > 0 and len(context) > max_context_chars)
    if truncated:
        context = context[:max_context_chars] + "\n...(truncated)"
    elapsed = (time.perf_counter() - started) * 1000
    metrics = context_token_metrics(context)
    metrics.update(
        {
            "included_meeting_count": len(included),
            "included_file_count": len(included),
            "full_context_source": source,
            "truncated": truncated,
            "truncated_from_chars": original_chars if truncated else None,
            "retrieval_ms": 0.0,
            "context_build_ms": round(elapsed, 3),
            "total_ms": round(elapsed, 3),
        }
    )
    return {
        "strategy": "full_context",
        "context": context,
        "included_meetings": included,
        "included_meeting_count": len(included),
        "included_file_count": len(included),
        "full_context_source": source,
        "truncated": truncated,
        "truncated_from_chars": original_chars if truncated else None,
        "metrics": metrics,
    }


def retrieve_lexical_rag(
    query: str,
    *,
    repo_root: Path | str,
    top_k: int = 6,
    chunk_size_lines: int = 20,
    chunk_overlap_lines: int = 5,
    max_context_chars: int = 5000,
) -> dict[str, Any]:
    started = time.perf_counter()
    loader = ObservatoryDataLoader(repo_root)
    query_terms = set(_tokens(query))
    scored: list[dict[str, Any]] = []
    for meeting_id, transcript in loader.load_transcripts().items():
        lines = _transcript_lines(transcript)
        for start_line, end_line, chunk_text in _line_chunks(
            lines,
            chunk_size_lines=chunk_size_lines,
            overlap_lines=chunk_overlap_lines,
        ):
            lower = chunk_text.lower().replace("_", " ").replace("-", " ")
            matched_terms = sorted(term for term in query_terms if term in lower)
            if not matched_terms:
                continue
            score = len(matched_terms) / max(1, len(query_terms))
            if str(query or "").strip().lower() in lower:
                score += 0.25
            scored.append(
                {
                    "chunk_id": f"rag-{meeting_id}-L{start_line}-L{end_line}",
                    "meeting_id": meeting_id,
                    "source_file": str(loader.transcript_root / f"{meeting_id}.txt"),
                    "start_line": start_line,
                    "end_line": end_line,
                    "text": chunk_text,
                    "score": round(score, 4),
                    "matched_terms": matched_terms,
                }
            )
    scored.sort(key=lambda row: (-float(row["score"]), str(row["meeting_id"]), int(row["start_line"])))
    selected = scored[: max(1, int(top_k))]
    context_parts = ["=== Traditional Lexical RAG ==="]
    for chunk in selected:
        context_parts.append(
            f"\n[{chunk['chunk_id']}] meeting={chunk['meeting_id']} "
            f"lines={chunk['start_line']}-{chunk['end_line']} score={chunk['score']}"
        )
        context_parts.append(str(chunk["text"]))
    context = "\n".join(context_parts)
    original_chars = len(context)
    truncated = len(context) > max_context_chars
    if truncated:
        context = context[:max_context_chars] + "\n...(truncated)"
    elapsed = (time.perf_counter() - started) * 1000
    metrics = context_token_metrics(context)
    metrics.update(
        {
            "retrieved_chunk_count": len(selected),
            "retrieval_ms": round(elapsed, 3),
            "context_build_ms": 0.0,
            "total_ms": round(elapsed, 3),
            "truncated": truncated,
            "truncated_from_chars": original_chars if truncated else None,
        }
    )
    return {
        "strategy": "rag_baseline",
        "context": context,
        "retrieved_chunk_count": len(selected),
        "retrieved_chunks": selected,
        "metrics": metrics,
    }

