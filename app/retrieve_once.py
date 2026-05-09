from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from google.genai import types

from config import GEMINI_API_KEY, MAX_RECALL_CONTEXT_CHARS, MODEL_NAME, EVALUATION_SYSTEM_PROMPT
from evaluation_prompts import build_evaluation_answer_prompt
from memory_context import retrieve_memory_context

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


INSUFFICIENT_MEMORY_ANSWER = "目前記憶中找不到足夠資訊回答此問題。"

SUFFICIENT_CONTEXT_PATTERNS = (
    re.compile(r"\bmatched L1:\s*L1-", re.IGNORECASE),
    re.compile(r"\bsource L1:\s*L1-", re.IGNORECASE),
    re.compile(r"\bL1-\d{4}-\d{3}\b"),
    re.compile(r"\bS-\d{4}-\d{3}\b"),
)

INSUFFICIENT_CONTEXT_MARKERS = (
    "（此問題不需要會議記憶檢索）",
    "（無相關記憶）",
    "（無長期記憶）",
    "（無短期記憶）",
    "（無相關短期記憶）",
    "short-term retrieval module is not available yet",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Retrieve meeting memory once and generate a direct answer."
    )
    parser.add_argument(
        "question",
        nargs="*",
        help="Question to answer. If omitted, the script reads stdin.",
    )
    parser.add_argument(
        "--model",
        default=MODEL_NAME,
        help=f"Gemini model name. Default: {MODEL_NAME}",
    )
    parser.add_argument(
        "--max-context-chars",
        type=int,
        default=MAX_RECALL_CONTEXT_CHARS,
        help=f"Maximum retrieved context characters. Default: {MAX_RECALL_CONTEXT_CHARS}",
    )
    parser.add_argument(
        "--show-context",
        action="store_true",
        help="Print retrieved memory context before the final answer.",
    )
    parser.add_argument(
        "--context-only",
        action="store_true",
        help="Only print retrieved memory context; do not generate an answer.",
    )
    return parser


def read_question(args: argparse.Namespace, stdin: object = sys.stdin) -> str:
    query = " ".join(args.question).strip()
    if query:
        return query
    return str(stdin.read()).strip()


def build_answer_prompt(*, query: str, memory_context: str) -> str:
    return build_evaluation_answer_prompt(
        query=query.strip(),
        context=memory_context.strip(),
        context_source="structured memory context",
    )


def has_sufficient_memory_context(memory_context: str) -> bool:
    context = str(memory_context or "").strip()
    if not context:
        return False
    if any(marker in context for marker in INSUFFICIENT_CONTEXT_MARKERS):
        return False
    return any(pattern.search(context) for pattern in SUFFICIENT_CONTEXT_PATTERNS)


def generate_answer(
    *,
    query: str,
    memory_context: str,
    api_key: str | Sequence[str] | None,
    model_name: str,
) -> str:
    from share_mem.l1.gemini_clients import create_gemini_client

    client = create_gemini_client(api_key)
    prompt = build_answer_prompt(query=query, memory_context=memory_context)
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
    return (response.text or "").strip() or "目前沒有可用回覆，請換個問法再試一次。"


def resolve_api_keys() -> list[str]:
    if GEMINI_API_KEY:
        return [GEMINI_API_KEY]
    from share_mem.l1.io_utils import load_api_keys

    return load_api_keys()


def run_once(argv: Sequence[str] | None = None, stdin: object = sys.stdin) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    query = read_question(args, stdin=stdin)
    if not query:
        parser.error("question is required via argv or stdin")

    api_keys = resolve_api_keys()
    retrieval_api_key: Any = api_keys if len(api_keys) > 1 else (api_keys[0] if api_keys else None)
    answer_api_key: str | Sequence[str] | None = retrieval_api_key

    memory_context = retrieve_memory_context(
        query=query,
        api_key=retrieval_api_key,
        model_name=args.model,
        max_context_chars=max(500, int(args.max_context_chars)),
    )
    if args.context_only:
        print(memory_context)
        return 0
    if args.show_context:
        print("=== Retrieved Memory Context ===")
        print(memory_context)
        print("\n=== Answer ===")

    if not has_sufficient_memory_context(memory_context):
        print(INSUFFICIENT_MEMORY_ANSWER)
        return 0

    print(
        generate_answer(
            query=query,
            memory_context=memory_context,
            api_key=answer_api_key,
            model_name=args.model,
        )
    )
    return 0


def main() -> None:
    raise SystemExit(run_once())


if __name__ == "__main__":
    main()
