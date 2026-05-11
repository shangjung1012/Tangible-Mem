from __future__ import annotations

import argparse
import os
from pathlib import Path

from .data_loader import REPO_ROOT
from .experiment_runner import run_experiment


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Memory Observatory comparison experiment.")
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository/artifact root to read share_mem, long_term, transcripts, and observatory outputs from.",
    )
    parser.add_argument("--queries", default="long_term/eval/long_term_retrieval_queries.jsonl")
    parser.add_argument("--out", default="memory_observatory/runs")
    parser.add_argument(
        "--strategies",
        default="full_context,rag_baseline,layered_memory",
        help="Comma-separated: full_context, rag_baseline, layered_memory",
    )
    parser.add_argument(
        "--retrieval-mode",
        choices=("hybrid", "lexical", "semantic"),
        default="hybrid",
        help="L1 seed retrieval mode. Hybrid fuses lexical and semantic hits when available.",
    )
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
        default=os.getenv("GEMINI_PLANNER_MODEL", ""),
        help="Model used only for LLM recall planning. Answer generation still uses --model.",
    )
    parser.add_argument(
        "--max-context-chars",
        type=int,
        default=0,
        help="Maximum context chars per strategy. Default 0 means unbounded for fair diagnostics.",
    )
    parser.add_argument("--rag-top-k", type=int, default=6)
    parser.add_argument(
        "--full-context-scope",
        choices=("gold", "all"),
        default="all",
        help="Full-context baseline scope. 'all' uses chronological all-transcript context; 'gold' is an explicit oracle upper bound.",
    )
    parser.add_argument(
        "--baseline-token-multiplier",
        type=float,
        default=0.0,
        help="If >0, cap full-context and RAG contexts to this multiplier of the layered context tokens per query.",
    )
    parser.add_argument(
        "--full-context-max-tokens",
        type=int,
        default=0,
        help="Absolute token cap for full-context baseline. Overrides --baseline-token-multiplier for full-context when >0.",
    )
    parser.add_argument(
        "--rag-max-context-tokens",
        type=int,
        default=0,
        help="Absolute token cap for RAG baseline. Overrides --baseline-token-multiplier for RAG when >0.",
    )
    parser.add_argument(
        "--budget-profile",
        default="",
        help="Optional layered-memory retrieval budget profile, e.g. large_corpus_tight.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    strategies = [item.strip() for item in args.strategies.split(",") if item.strip()]
    result = run_experiment(
        repo_root=Path(args.repo_root),
        queries_path=Path(args.queries),
        out=Path(args.out),
        strategies=strategies,
        retrieval_mode=args.retrieval_mode,
        no_llm=not bool(args.use_llm_planner and not args.no_llm),
        generate_answers=args.generate_answers,
        model=args.model,
        planner_model=args.planner_model,
        max_context_chars=args.max_context_chars,
        rag_top_k=args.rag_top_k,
        budget_profile=args.budget_profile,
        full_context_scope=args.full_context_scope,
        baseline_token_multiplier=args.baseline_token_multiplier,
        full_context_max_tokens=args.full_context_max_tokens,
        rag_max_context_tokens=args.rag_max_context_tokens,
    )
    print(f"wrote Memory Observatory run: {Path(args.out) / result['run_id']}")


if __name__ == "__main__":
    main()
