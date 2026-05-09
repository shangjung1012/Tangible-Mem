from __future__ import annotations

import argparse
from pathlib import Path

from .data_loader import REPO_ROOT
from .experiment_runner import run_experiment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Memory Observatory comparison experiment.")
    parser.add_argument("--queries", default="long_term/eval/long_term_retrieval_queries.jsonl")
    parser.add_argument("--out", default="memory_observatory/runs")
    parser.add_argument(
        "--strategies",
        default="full_context,rag_baseline,layered_memory",
        help="Comma-separated: full_context, rag_baseline, layered_memory",
    )
    parser.add_argument("--retrieval-mode", choices=("lexical", "semantic"), default="lexical")
    parser.add_argument("--no-llm", action="store_true", help="Do not call planner, embedding API, or final answer LLM.")
    parser.add_argument("--generate-answers", action="store_true")
    parser.add_argument("--model", default="gemini-2.5-pro")
    parser.add_argument("--max-context-chars", type=int, default=4000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    strategies = [item.strip() for item in args.strategies.split(",") if item.strip()]
    result = run_experiment(
        repo_root=REPO_ROOT,
        queries_path=Path(args.queries),
        out=Path(args.out),
        strategies=strategies,
        retrieval_mode=args.retrieval_mode,
        no_llm=args.no_llm or not args.generate_answers,
        generate_answers=args.generate_answers,
        model=args.model,
        max_context_chars=args.max_context_chars,
    )
    print(f"wrote Memory Observatory run: {Path(args.out) / result['run_id']}")


if __name__ == "__main__":
    main()
