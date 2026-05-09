from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Sequence

from google.genai import types

from config import MODEL_NAME, EVALUATION_SYSTEM_PROMPT
from evaluation_prompts import build_evaluation_answer_prompt

ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = ROOT / "long_term"
if str(LONG_TERM_DIR) not in sys.path:
    sys.path.insert(0, str(LONG_TERM_DIR))

from embedder import EmbedCache, cosine_similarity, embed_text  # noqa: E402

DEFAULT_TRANSCRIPT_DIR = ROOT / "meeting_recording" / "transcript" / "grace"
DEFAULT_RAG_EMBED_CACHE_PATH = ROOT / "doc" / "evaluation_runs" / "cache" / "transcript_rag_embeddings.json"

TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)

def parse_meeting_ids(value: str | Sequence[str]) -> list[str]:
    if isinstance(value, str):
        raw_parts = re.split(r"[\s,;]+", value)
    else:
        raw_parts = [str(part) for part in value]
    output: list[str] = []
    for part in raw_parts:
        clean = part.strip()
        if clean and clean not in output:
            output.append(clean)
    return output


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(str(text or "").lower())]


def _load_transcript(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def load_transcripts(transcript_dir: Path | str = DEFAULT_TRANSCRIPT_DIR) -> dict[str, str]:
    root = Path(transcript_dir)
    transcripts: dict[str, str] = {}
    for path in sorted(root.glob("*.txt")):
        transcripts[path.stem] = _load_transcript(path)
    return transcripts


def chunk_text(text: str, *, chunk_chars: int = 1800, overlap_chars: int = 250) -> list[str]:
    compact = str(text or "").strip()
    if not compact:
        return []
    chunk_chars = max(300, chunk_chars)
    overlap_chars = max(0, min(overlap_chars, chunk_chars // 2))
    chunks: list[str] = []
    start = 0
    while start < len(compact):
        end = min(len(compact), start + chunk_chars)
        chunks.append(compact[start:end].strip())
        if end >= len(compact):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def _score_chunk(query_terms: set[str], chunk: str) -> float:
    if not query_terms:
        return 0.0
    chunk_lower = chunk.lower().replace("_", " ").replace("-", " ")
    hits = sum(1 for term in query_terms if term in chunk_lower)
    if hits == 0:
        return 0.0
    chunk_terms = set(_tokens(chunk_lower))
    overlap = len(query_terms & chunk_terms)
    return hits + overlap * 0.5


def retrieve_lexical_rag_context(
    query: str,
    *,
    transcript_dir: Path | str = DEFAULT_TRANSCRIPT_DIR,
    top_k: int = 6,
    max_context_chars: int = 5000,
) -> str:
    """Lexical raw-transcript RAG fallback without L2/L3 structure."""
    transcripts = load_transcripts(transcript_dir)
    query_terms = set(_tokens(query))
    scored: list[tuple[float, str, int, str]] = []
    for meeting_id, transcript in transcripts.items():
        for index, chunk in enumerate(chunk_text(transcript), start=1):
            score = _score_chunk(query_terms, chunk)
            if score > 0:
                scored.append((round(score, 4), meeting_id, index, chunk))
    scored.sort(key=lambda row: (-row[0], row[1], row[2]))
    selected = scored[: max(1, top_k)]
    if not selected:
        return "（lexical RAG baseline 找不到相關 transcript chunk）"

    parts = ["=== Lexical RAG Transcript Baseline ==="]
    for score, meeting_id, index, chunk in selected:
        parts.append(f"\n[{meeting_id}#chunk-{index}] score={score}")
        parts.append(chunk)
    context = "\n".join(parts)
    if len(context) > max_context_chars:
        return context[:max_context_chars] + "\n...(truncated)"
    return context


def _iter_transcript_chunks(
    transcript_dir: Path | str = DEFAULT_TRANSCRIPT_DIR,
) -> list[dict[str, Any]]:
    transcripts = load_transcripts(transcript_dir)
    rows: list[dict[str, Any]] = []
    for meeting_id, transcript in transcripts.items():
        for index, chunk in enumerate(chunk_text(transcript), start=1):
            if chunk:
                rows.append(
                    {
                        "meeting_id": meeting_id,
                        "chunk_id": f"{meeting_id}#chunk-{index}",
                        "chunk_index": index,
                        "text": chunk,
                    }
                )
    return rows


def retrieve_embedding_rag_context(
    query: str,
    api_key: str | Sequence[str] | None,
    *,
    transcript_dir: Path | str = DEFAULT_TRANSCRIPT_DIR,
    top_k: int = 6,
    max_context_chars: int = 5000,
    cache_path: Path | str = DEFAULT_RAG_EMBED_CACHE_PATH,
) -> str:
    """Embedding raw-transcript RAG baseline without L1/L2/L3 structure."""
    chunks = _iter_transcript_chunks(transcript_dir)
    if not chunks:
        return "（embedding RAG baseline 找不到 transcript chunks）"

    cache = EmbedCache(Path(cache_path))
    try:
        query_emb = embed_text(query, api_key, cache)
        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in chunks:
            chunk_text_value = (
                f"meeting_id: {chunk['meeting_id']}\n"
                f"chunk_id: {chunk['chunk_id']}\n"
                f"{chunk['text']}"
            )
            chunk_emb = embed_text(chunk_text_value, api_key, cache)
            scored.append((cosine_similarity(query_emb, chunk_emb), chunk))
        cache.save()
    except Exception:
        cache.save()
        return retrieve_lexical_rag_context(
            query,
            transcript_dir=transcript_dir,
            top_k=top_k,
            max_context_chars=max_context_chars,
        )

    scored.sort(key=lambda row: (-row[0], row[1]["meeting_id"], row[1]["chunk_index"]))
    selected = scored[: max(1, top_k)]
    parts = ["=== Embedding RAG Transcript Baseline ==="]
    for score, chunk in selected:
        parts.append(f"\n[{chunk['chunk_id']}] cosine={score:.4f}")
        parts.append(str(chunk["text"]))
    context = "\n".join(parts)
    if len(context) > max_context_chars:
        return context[:max_context_chars] + "\n...(truncated)"
    return context


def retrieve_plain_rag_context(
    query: str,
    *,
    api_key: str | Sequence[str] | None = None,
    transcript_dir: Path | str = DEFAULT_TRANSCRIPT_DIR,
    top_k: int = 6,
    max_context_chars: int = 5000,
    cache_path: Path | str = DEFAULT_RAG_EMBED_CACHE_PATH,
    mode: str = "embedding",
) -> str:
    """Raw-transcript RAG baseline. Defaults to embedding similarity."""
    if mode == "lexical":
        return retrieve_lexical_rag_context(
            query,
            transcript_dir=transcript_dir,
            top_k=top_k,
            max_context_chars=max_context_chars,
        )
    if mode != "embedding":
        raise ValueError(f"Unsupported RAG mode: {mode}")
    return retrieve_embedding_rag_context(
        query,
        api_key,
        transcript_dir=transcript_dir,
        top_k=top_k,
        max_context_chars=max_context_chars,
        cache_path=cache_path,
    )


def retrieve_full_transcript_context(
    meeting_ids: str | Sequence[str],
    *,
    transcript_dir: Path | str = DEFAULT_TRANSCRIPT_DIR,
    max_context_chars: int = 0,
    scope: str = "gold",
) -> str:
    """Full-transcript baseline.

    scope="gold" uses the row's oracle meeting ids.
    scope="all" uses every transcript in the configured transcript directory.
    """
    transcripts = load_transcripts(transcript_dir)
    if scope == "all":
        ids = sorted(transcripts)
    elif scope == "gold":
        ids = parse_meeting_ids(meeting_ids)
    else:
        raise ValueError(f"Unsupported full transcript scope: {scope}")

    parts = ["=== Full Transcript Baseline ==="]
    for meeting_id in ids:
        transcript = transcripts.get(meeting_id, "")
        if not transcript:
            continue
        parts.append(f"\n--- meeting {meeting_id} ---")
        parts.append(transcript.strip())
    if len(parts) == 1:
        return "（full transcript baseline 找不到指定會議逐字稿）"
    context = "\n".join(parts)
    if max_context_chars > 0 and len(context) > max_context_chars:
        return context[:max_context_chars] + "\n...(truncated)"
    return context


def generate_baseline_answer(
    *,
    query: str,
    context: str,
    baseline_name: str,
    api_key: str | Sequence[str] | None,
    model_name: str = MODEL_NAME,
) -> str:
    from share_mem.l1.gemini_clients import create_gemini_client

    client = create_gemini_client(api_key)
    prompt = build_evaluation_answer_prompt(
        context_source=f"baseline: {baseline_name}",
        query=query.strip(),
        context=context.strip(),
    )
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=EVALUATION_SYSTEM_PROMPT,
            temperature=0.2,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="NONE")
            ),
        ),
    )
    return (response.text or "").strip() or "目前 baseline context 不足以回答。"
