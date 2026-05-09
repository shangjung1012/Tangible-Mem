from __future__ import annotations

import argparse
import os
from pathlib import Path

from .data_loader import REPO_ROOT
from .experiment_runner import run_experiment


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Memory Observatory comparison experiment.")
    parser.add_argument("--queries", default="long_term/eval/long_term_retrieval_queries.jsonl")
    parser.add_argument("--out", default="memory_observatory/runs")
    parser.add_argument(
        "--strategies",
        default="full_context,rag_baseline,layered_memory",
        help="Comma-separated: full_context, rag_baseline, layered_memory",
    )
    parser.add_argument("--retrieval-mode", choices=("lexical", "semantic"), default="lexical")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Keep the layered retrieval planner heuristic. This is the default; retained for compatibility.",
    )
    parser.add_argument(
        "--use-llm-planner",
        action="store_true",
        help="Opt in to Gemini recall planning. Answer generation is still controlled by --generate-answers.",
    )
    parser.add_argument("--generate-answers", action="store_true")
    parser.add_argument("--model", default="gemini-2.5-pro")
    parser.add_argument(
        "--planner-model",
        default=os.getenv("GEMINI_PLANNER_MODEL", "gemini-2.5-flash"),
        help="Model used only for LLM recall planning. Answer generation still uses --model.",
    )
    parser.add_argument("--max-context-chars", type=int, default=4000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    strategies = [item.strip() for item in args.strategies.split(",") if item.strip()]
    result = run_experiment(
        repo_root=REPO_ROOT,
        queries_path=Path(args.queries),
        out=Path(args.out),
        strategies=strategies,
        retrieval_mode=args.retrieval_mode,
        no_llm=not bool(args.use_llm_planner and not args.no_llm),
        generate_answers=args.generate_answers,
        model=args.model,
        planner_model=args.planner_model,
        max_context_chars=args.max_context_chars,
    )
    print(f"wrote Memory Observatory run: {Path(args.out) / result['run_id']}")


if __name__ == "__main__":
    main()
