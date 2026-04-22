"""A/B test for recall prompt injection.

Usage examples:
  PYTHONPATH=long_term UV_CACHE_DIR=/tmp/uv-cache uv run python \
    long_term/scripts/eval_prompt_injection.py \
    --question "錄音增益問題的處理過程是什麼？" \
    --show-injected-context

  # show-only (no LLM answer generation)
  PYTHONPATH=long_term UV_CACHE_DIR=/tmp/uv-cache uv run python \
    long_term/scripts/eval_prompt_injection.py \
    --question "目前有哪些待辦事項？" \
    --show-only
"""

from __future__ import annotations

import argparse
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from embedder import EmbedCache
from gemini_clients import create_gemini_client
from io_utils import load_api_keys, load_tree
from recall import format_recall_for_prompt, recall
from recall_planner import plan_recall


BASE_SYSTEM_PROMPT = """你是一名研究導師，回答時請：
1) 先直接回答問題
2) 再用 1-3 點補充推理依據
3) 若資訊不足請明確說明"""


def _is_retryable_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {429, 500, 502, 503, 504}:
        return True
    msg = str(exc).upper()
    return any(tok in msg for tok in ("429", "500", "502", "503", "504", "UNAVAILABLE", "RATE LIMIT"))


def _generate_with_retry(
    client: Any,
    model_name: str,
    system_prompt: str,
    user_query: str,
    max_retries: int = 6,
) -> str:
    cfg: dict[str, Any] = {
        "temperature": 0.1,
        "system_instruction": system_prompt,
    }

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=user_query,
                config=cfg,
            )
            return (resp.text or "").strip()
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries or not _is_retryable_error(exc):
                break
            wait_s = min(90.0, 2.0 * (2 ** (attempt - 1))) + random.uniform(0.0, 1.5)
            print(
                f"LLM busy ({type(exc).__name__}), retry {attempt}/{max_retries} in {wait_s:.1f}s..."
            )
            time.sleep(wait_s)

    if last_exc:
        raise last_exc
    raise RuntimeError("Unexpected failure in _generate_with_retry")


def _build_injected_system_prompt(context: str) -> str:
    return (
        BASE_SYSTEM_PROMPT
        + "\n\n以下是記憶系統檢索出的背景（若與問題不相關可忽略）：\n"
        + context
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="A/B test recall prompt injection effect.")
    p.add_argument("--question", required=True, help="User question to test")
    p.add_argument("--tree", default="long_term/tree.json", help="Path to tree.json")
    p.add_argument(
        "--model",
        default="",
        help="LLM model for answer generation (default from GEMINI_MODEL or gemini-2.5-flash)",
    )
    p.add_argument("--show-injected-context", action="store_true", help="Print full injected recall context")
    p.add_argument("--show-only", action="store_true", help="Only show recall context; skip A/B answer generation")
    p.add_argument("--save", action="store_true", help="Save report to long_term/snapshots/injection_eval/")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    api_keys = load_api_keys()
    model_name = args.model.strip() or "gemini-2.5-flash"
    tree = load_tree(Path(args.tree))

    plan = plan_recall(args.question, api_keys, model_name=model_name)
    cache = EmbedCache()
    recall_result = recall(
        query=args.question,
        plan=plan,
        tree=tree,
        api_key=api_keys,
        model_name=model_name,
        embed_cache=cache,
    )
    cache.save()

    injected_context = format_recall_for_prompt(recall_result)

    print("=== Recall Plan ===")
    print("complexity:", plan.get("complexity"))
    print("targets:", plan.get("search_targets"))
    print("keywords:", plan.get("keywords"))
    if "type_filter" in plan:
        print("type_filter:", plan.get("type_filter"))

    print("\n=== Retrieved Counts ===")
    print("long_term_l1:", len(recall_result.get("long_term_l1", [])))
    print("long_term_l2:", len(recall_result.get("long_term_l2", [])))
    print("short_term_results:", len(recall_result.get("short_term_results", [])))

    if args.show_injected_context or args.show_only:
        print("\n=== Injected Context (format_recall_for_prompt) ===")
        print(injected_context)
    else:
        preview = injected_context[:1200]
        if len(injected_context) > 1200:
            preview += "\n... (truncated)"
        print("\n=== Injected Context Preview ===")
        print(preview)

    if args.show_only:
        return

    client = create_gemini_client(api_keys)
    ans_no_injection = _generate_with_retry(
        client=client,
        model_name=model_name,
        system_prompt=BASE_SYSTEM_PROMPT,
        user_query=args.question,
    )

    ans_with_injection = _generate_with_retry(
        client=client,
        model_name=model_name,
        system_prompt=_build_injected_system_prompt(injected_context),
        user_query=args.question,
    )

    print("\n=== A/B Answers ===")
    print("\n[No Injection]")
    print(ans_no_injection)
    print("\n[With Recall Injection]")
    print(ans_with_injection)

    if args.save:
        out_dir = Path("long_term/snapshots/injection_eval")
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = out_dir / f"{ts}.md"
        out.write_text(
            "\n".join(
                [
                    f"# Injection Eval {ts}",
                    "",
                    f"Question: {args.question}",
                    f"Model: {model_name}",
                    "",
                    "## Plan",
                    str(plan),
                    "",
                    "## Injected Context",
                    injected_context,
                    "",
                    "## No Injection",
                    ans_no_injection,
                    "",
                    "## With Recall Injection",
                    ans_with_injection,
                ]
            ),
            encoding="utf-8",
        )
        print(f"\nSaved report: {out}")


if __name__ == "__main__":
    main()
