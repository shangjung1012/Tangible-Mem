from __future__ import annotations

import sys
from pathlib import Path

from config import GEMINI_API_KEY, MAX_RECALL_CONTEXT_CHARS, MODEL_NAME
from memory_context import retrieve_long_term_context
from runtime_log import log_tool_result

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from short_term.retrieval.short_term_context import retrieve_short_term_context


def get_short_term_memory_context(
    query: str,
    retrieval_mode: str = "hybrid",
    top_k: int = 6,
) -> dict[str, str]:
    """Retrieve short-term memory context from short-term memory storage.

    Use this for recent status, owners, TODOs, latest decisions, and near-term progress.

    The short-term pipeline is SQLite-first; JSON is only a fallback/export path.

    Args:
        query: User question.
        retrieval_mode: lexical | semantic | hybrid (default: hybrid).
        top_k: Number of short-term chunks to retrieve.
    """
    context = retrieve_short_term_context(
        query=query,
        api_key=GEMINI_API_KEY,
        retrieval_mode=retrieval_mode,
        top_k=top_k,
        max_context_chars=MAX_RECALL_CONTEXT_CHARS,
    )
    log_tool_result("get_short_term_memory_context", query, context)
    return {"short_term_context": context}


def get_long_term_memory_context(query: str) -> dict[str, str]:
    """Retrieve long-term memory context from temporal memory tree.

    Use this for cross-meeting history, method evolution, rationale tracing,
    and long time-range project questions.
    """
    context = retrieve_long_term_context(
        query=query,
        api_key=GEMINI_API_KEY,
        model_name=MODEL_NAME,
        max_context_chars=MAX_RECALL_CONTEXT_CHARS,
    )
    log_tool_result("get_long_term_memory_context", query, context)
    return {"long_term_context": context}
