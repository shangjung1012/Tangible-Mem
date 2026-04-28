from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google import genai

try:
    from .genai_client import create_genai_client, load_genai_config
    from .genai_retry import call_with_retry
    from .sqlite_store import DEFAULT_DB_PATH, load_memory_with_fallback
except ImportError:  # pragma: no cover - script execution fallback
    from genai_client import create_genai_client, load_genai_config
    from genai_retry import call_with_retry
    from sqlite_store import DEFAULT_DB_PATH, load_memory_with_fallback


DEFAULT_EMBEDDING_MODEL_NAME = "gemini-embedding-001"
ROOT = Path(__file__).resolve().parents[1]
SHORT_TERM_MEMORY_PATH = ROOT / "short_term" / "current_memory.json"
SHORT_TERM_DB_PATH = DEFAULT_DB_PATH
DEFAULT_EMBEDDING_CACHE_PATH = ROOT / "short_term" / ".embedding_cache.json"


@dataclass(slots=True)
class MemoryChunk:
    chunk_id: str
    chunk_type: str
    title: str
    text: str
    metadata: dict[str, str]


@dataclass(slots=True)
class ScoredChunk:
    chunk: MemoryChunk
    score: float
    lexical_score: float | None = None
    semantic_score: float | None = None


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_short_term_memory() -> dict[str, Any]:
    try:
        memory, _ = load_memory_with_fallback(
            db_path=SHORT_TERM_DB_PATH,
            json_path=SHORT_TERM_MEMORY_PATH,
            bootstrap_from_json=True,
        )
        return memory
    except Exception:
        return load_json_object(SHORT_TERM_MEMORY_PATH)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def extract_terms(text: str) -> Counter[str]:
    normalized = normalize_text(text)
    terms: list[str] = []

    for token in re.findall(r"[a-z0-9_]{2,}", normalized):
        terms.append(token)

    for block in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if len(block) == 1:
            terms.append(block)
            continue
        terms.append(block)
        for size in (2, 3):
            if len(block) < size:
                continue
            for idx in range(len(block) - size + 1):
                terms.append(block[idx : idx + size])

    return Counter(terms)


def build_chunks(memory: dict[str, Any]) -> list[MemoryChunk]:
    chunks: list[MemoryChunk] = []

    history_ids = memory.get("meeting_history_ids", [])
    meeting_window = memory.get("meeting_window", [])
    next_focus = memory.get("next_meeting_focus", [])

    overview_text = "\n".join(
        [
            f"memory_version: {memory.get('memory_version', '')}",
            f"last_updated_utc: {memory.get('last_updated_utc', '')}",
            f"last_updated_meeting_id: {memory.get('last_updated_meeting_id', '')}",
            f"meeting_history_ids: {', '.join(history_ids)}",
            f"meeting_window_ids: {', '.join(str(row.get('meeting_id', '')) for row in meeting_window if isinstance(row, dict))}",
            f"action_items_count: {len(memory.get('action_items', []))}",
            f"method_changes_count: {len(memory.get('method_changes', []))}",
            f"experiment_todos_count: {len(memory.get('experiment_todos', []))}",
            f"next_meeting_focus_count: {len(next_focus)}",
        ]
    )
    chunks.append(
        MemoryChunk(
            chunk_id="overview",
            chunk_type="overview",
            title="短期記憶總覽",
            text=overview_text,
            metadata={"scope": "global"},
        )
    )

    for meeting in meeting_window:
        if not isinstance(meeting, dict):
            continue
        meeting_id = str(meeting.get("meeting_id", "")).strip()
        summary = str(meeting.get("summary", "")).strip()
        key_points = meeting.get("key_points", [])
        open_questions = meeting.get("open_questions", [])

        meeting_text = "\n".join(
            [
                f"meeting_id: {meeting_id}",
                f"source_file: {meeting.get('source_file', '')}",
                f"summary: {summary}",
                "key_points:",
                *[f"- {point}" for point in key_points if point],
                "open_questions:",
                *[f"- {question}" for question in open_questions if question],
            ]
        )
        chunks.append(
            MemoryChunk(
                chunk_id=f"meeting:{meeting_id}",
                chunk_type="meeting",
                title=f"會議 {meeting_id}",
                text=meeting_text,
                metadata={"meeting_id": meeting_id},
            )
        )

    for item in memory.get("action_items", []):
        if not isinstance(item, dict):
            continue
        history_rows = item.get("history", [])
        recent_history = []
        if isinstance(history_rows, list):
            recent_history = history_rows[-3:]

        item_id = str(item.get("item_id", "")).strip()
        item_text = "\n".join(
            [
                f"item_id: {item_id}",
                f"title: {item.get('title', '')}",
                f"status: {item.get('status', '')}",
                f"priority: {item.get('priority', '')}",
                f"owner: {item.get('owner', '')}",
                f"proposer: {item.get('proposer', '')}",
                f"created_meeting_id: {item.get('created_meeting_id', '')}",
                f"last_updated_meeting_id: {item.get('last_updated_meeting_id', '')}",
                f"dependencies: {', '.join(item.get('dependencies', []))}",
                f"detail: {item.get('detail', '')}",
                f"evidence: {item.get('evidence', '')}",
                "recent_history:",
                *[
                    f"- v{row.get('version', '')} {row.get('meeting_id', '')}: {row.get('change', '')}"
                    for row in recent_history
                    if isinstance(row, dict)
                ],
            ]
        )
        chunks.append(
            MemoryChunk(
                chunk_id=f"action:{item_id}",
                chunk_type="action_item",
                title=f"Action Item {item_id}: {item.get('title', '')}",
                text=item_text,
                metadata={
                    "item_id": item_id,
                    "last_updated_meeting_id": str(
                        item.get("last_updated_meeting_id", "")
                    ).strip(),
                },
            )
        )

    for change in memory.get("method_changes", []):
        if not isinstance(change, dict):
            continue
        change_id = str(change.get("change_id", "")).strip()
        change_text = "\n".join(
            [
                f"change_id: {change_id}",
                f"topic: {change.get('topic', '')}",
                f"status: {change.get('status', '')}",
                f"meeting_id: {change.get('meeting_id', '')}",
                f"before: {change.get('before', '')}",
                f"after: {change.get('after', '')}",
                f"reason: {change.get('reason', '')}",
                f"evidence: {change.get('evidence', '')}",
            ]
        )
        chunks.append(
            MemoryChunk(
                chunk_id=f"method:{change_id}",
                chunk_type="method_change",
                title=f"Method Change {change_id}: {change.get('topic', '')}",
                text=change_text,
                metadata={"change_id": change_id},
            )
        )

    for todo in memory.get("experiment_todos", []):
        if not isinstance(todo, dict):
            continue
        todo_id = str(todo.get("todo_id", "")).strip()
        todo_text = "\n".join(
            [
                f"todo_id: {todo_id}",
                f"description: {todo.get('description', '')}",
                f"status: {todo.get('status', '')}",
                f"owner: {todo.get('owner', '')}",
                f"meeting_id: {todo.get('meeting_id', '')}",
                f"related_action_item_ids: {', '.join(todo.get('related_action_item_ids', []))}",
                f"evidence: {todo.get('evidence', '')}",
            ]
        )
        chunks.append(
            MemoryChunk(
                chunk_id=f"todo:{todo_id}",
                chunk_type="experiment_todo",
                title=f"Experiment TODO {todo_id}",
                text=todo_text,
                metadata={"todo_id": todo_id},
            )
        )

    for index, focus in enumerate(next_focus, start=1):
        if not focus:
            continue
        chunks.append(
            MemoryChunk(
                chunk_id=f"focus:{index:03d}",
                chunk_type="next_meeting_focus",
                title=f"下次會議焦點 {index}",
                text=f"next_meeting_focus[{index}]: {focus}",
                metadata={"focus_index": str(index)},
            )
        )

    return chunks


def score_chunk(question: str, chunk: MemoryChunk) -> float:
    question_norm = normalize_text(question)
    chunk_norm = normalize_text(f"{chunk.title}\n{chunk.text}")
    question_terms = extract_terms(question)
    chunk_terms = extract_terms(chunk_norm)

    overlap = 0.0
    for term, query_count in question_terms.items():
        if term not in chunk_terms:
            continue
        boost = 1.0
        if len(term) >= 4:
            boost = 1.5
        if re.fullmatch(r"[a-z]+\d+", term):
            boost = 3.0
        overlap += min(query_count, chunk_terms[term]) * boost

    substring_bonus = 0.0
    if question_norm and question_norm in chunk_norm:
        substring_bonus += 8.0

    metadata_bonus = 0.0
    for value in chunk.metadata.values():
        value_norm = normalize_text(value)
        if value_norm and value_norm in question_norm:
            metadata_bonus += 5.0

    title_bonus = 0.0
    title_norm = normalize_text(chunk.title)
    for term in question_terms:
        if term and term in title_norm:
            title_bonus += 1.0

    return overlap + substring_bonus + metadata_bonus + title_bonus


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(l * r for l, r in zip(left, right))
    left_norm = math.sqrt(sum(l * l for l in left))
    right_norm = math.sqrt(sum(r * r for r in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def normalize_scores(scores: list[float]) -> list[float]:
    if not scores:
        return []
    low = min(scores)
    high = max(scores)
    if math.isclose(low, high):
        return [1.0 if score > 0 else 0.0 for score in scores]
    return [(score - low) / (high - low) for score in scores]


def load_embedding_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"entries": {}}
    if not isinstance(data, dict):
        return {"entries": {}}
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return {"entries": {}}
    return {"entries": entries}


def save_embedding_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extract_embedding_values(response: Any) -> list[list[float]]:
    embeddings = getattr(response, "embeddings", None)
    if embeddings:
        values_list: list[list[float]] = []
        for embedding in embeddings:
            values = getattr(embedding, "values", None)
            if values:
                values_list.append(list(values))
        return values_list

    single_embedding = getattr(response, "embedding", None)
    if single_embedding is not None:
        values = getattr(single_embedding, "values", None)
        if values:
            return [list(values)]
    return []


def embed_texts(
    client: genai.Client,
    model_name: str,
    texts: list[str],
    task_type: str,
) -> list[list[float]]:
    if not texts:
        return []
    response = call_with_retry(
        lambda: client.models.embed_content(
            model=model_name,
            contents=texts,
            config={"task_type": task_type},
        ),
        operation_name=f"short-term-context embed_content {task_type}",
    )
    vectors = extract_embedding_values(response)
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"Embedding response count mismatch: expected {len(texts)}, got {len(vectors)}"
        )
    return vectors


def get_chunk_embedding_key(chunk: MemoryChunk, embedding_model: str) -> str:
    payload = "\n".join([chunk.chunk_id, chunk.chunk_type, chunk.title, chunk.text])
    return f"{embedding_model}:doc:{chunk.chunk_id}:{hash_text(payload)}"


def get_chunk_embeddings(
    client: genai.Client,
    embedding_model: str,
    chunks: list[MemoryChunk],
    cache_path: Path,
) -> list[list[float]]:
    cache = load_embedding_cache(cache_path)
    entries: dict[str, Any] = cache["entries"]

    vectors: list[list[float] | None] = [None] * len(chunks)
    missing_indices: list[int] = []
    missing_texts: list[str] = []

    for index, chunk in enumerate(chunks):
        key = get_chunk_embedding_key(chunk, embedding_model)
        cached = entries.get(key)
        if isinstance(cached, list) and cached:
            vectors[index] = [float(value) for value in cached]
            continue
        missing_indices.append(index)
        missing_texts.append("\n".join([chunk.title, chunk.text]))

    if missing_texts:
        embedded = embed_texts(
            client=client,
            model_name=embedding_model,
            texts=missing_texts,
            task_type="RETRIEVAL_DOCUMENT",
        )
        for index, vector in zip(missing_indices, embedded):
            chunk = chunks[index]
            key = get_chunk_embedding_key(chunk, embedding_model)
            entries[key] = vector
            vectors[index] = vector
        save_embedding_cache(cache_path, cache)

    final_vectors: list[list[float]] = []
    for vector in vectors:
        if vector is None:
            raise RuntimeError("Missing chunk embedding after cache fill.")
        final_vectors.append(vector)
    return final_vectors


def semantic_scores_for_chunks(
    client: genai.Client,
    embedding_model: str,
    cache_path: Path,
    question: str,
    chunks: list[MemoryChunk],
) -> list[float]:
    query_vectors = embed_texts(
        client=client,
        model_name=embedding_model,
        texts=[question],
        task_type="RETRIEVAL_QUERY",
    )
    query_vector = query_vectors[0]
    chunk_vectors = get_chunk_embeddings(
        client=client,
        embedding_model=embedding_model,
        chunks=chunks,
        cache_path=cache_path,
    )
    return [cosine_similarity(query_vector, chunk_vector) for chunk_vector in chunk_vectors]


def retrieve_chunks(
    chunks: list[MemoryChunk],
    question: str,
    top_k: int,
    retrieval_mode: str,
    client: genai.Client | None,
    embedding_model: str,
    embedding_cache_path: Path,
) -> list[ScoredChunk]:
    lexical_scores = [score_chunk(question, chunk) for chunk in chunks]

    semantic_scores: list[float] | None = None
    if retrieval_mode in {"semantic", "hybrid"}:
        if client is None:
            raise RuntimeError(
                "Semantic retrieval requires a Google Gen AI client."
            )
        semantic_scores = semantic_scores_for_chunks(
            client=client,
            embedding_model=embedding_model,
            cache_path=embedding_cache_path,
            question=question,
            chunks=chunks,
        )

    if retrieval_mode == "lexical":
        final_scores = lexical_scores
    elif retrieval_mode == "semantic":
        final_scores = semantic_scores or [0.0] * len(chunks)
    else:
        lexical_norm = normalize_scores(lexical_scores)
        semantic_norm = normalize_scores(semantic_scores or [0.0] * len(chunks))
        final_scores = [
            (0.35 * lexical_score) + (0.65 * semantic_score)
            for lexical_score, semantic_score in zip(lexical_norm, semantic_norm)
        ]

    scored = [
        (
            final_scores[index],
            index,
            ScoredChunk(
                chunk=chunk,
                score=final_scores[index],
                lexical_score=lexical_scores[index],
                semantic_score=None if semantic_scores is None else semantic_scores[index],
            ),
        )
        for index, chunk in enumerate(chunks)
    ]
    scored.sort(key=lambda row: (row[0], -row[1]), reverse=True)

    positives = [row[2] for row in scored if row[0] > 0][:top_k]
    if positives:
        return positives

    fallback = [row[2] for row in scored if row[2].chunk.chunk_type == "meeting"][:top_k]
    if fallback:
        return fallback
    return [row[2] for row in scored[:top_k]]


def format_context(chunks: list[ScoredChunk]) -> str:
    return "\n\n".join(
        [
            "\n".join(
                [
                    f"[{index}] chunk_id={scored.chunk.chunk_id}",
                    f"type={scored.chunk.chunk_type}",
                    f"title={scored.chunk.title}",
                    f"retrieval_score={scored.score:.4f}",
                    "content:",
                    scored.chunk.text,
                ]
            )
            for index, scored in enumerate(chunks, start=1)
        ]
    )


def retrieve_short_term_context(
    query: str,
    api_key: str | None = None,
    retrieval_mode: str = "hybrid",
    top_k: int = 6,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL_NAME,
    embedding_cache_path: Path = DEFAULT_EMBEDDING_CACHE_PATH,
    max_context_chars: int = 4000,
) -> str:
    retrieval_mode = (retrieval_mode or "hybrid").lower()
    if retrieval_mode not in {"lexical", "semantic", "hybrid"}:
        retrieval_mode = "hybrid"

    memory = load_short_term_memory()
    if not memory:
        return "（無短期記憶）"

    chunks = build_chunks(memory)
    client: genai.Client | None = None
    if retrieval_mode in {"semantic", "hybrid"}:
        client = create_genai_client(load_genai_config(api_key=api_key))

    retrieved = retrieve_chunks(
        chunks=chunks,
        question=query,
        top_k=max(1, top_k),
        retrieval_mode=retrieval_mode,
        client=client,
        embedding_model=embedding_model,
        embedding_cache_path=embedding_cache_path,
    )
    context = format_context(retrieved)
    if len(context) > max_context_chars:
        return context[:max_context_chars] + "\n...(truncated)"
    return context if context else "（無短期記憶）"
