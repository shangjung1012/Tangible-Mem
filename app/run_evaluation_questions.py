from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from retrieve_once import (
    INSUFFICIENT_MEMORY_ANSWER,
    generate_answer,
    has_sufficient_memory_context,
    resolve_api_keys,
)
from config import MAX_RECALL_CONTEXT_CHARS, MODEL_NAME
from memory_context import retrieve_memory_context
from baseline_retrieval import (
    generate_baseline_answer,
    retrieve_full_transcript_context,
    retrieve_plain_rag_context,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "doc" / "evaluation_questions_0307_0506.csv"
DEFAULT_OUTPUT = ROOT / "doc" / "evaluation_runs" / "latest_answers.csv"
DEFAULT_CONTEXT_DIR = ROOT / "doc" / "evaluation_runs" / "contexts"

L1_RE = re.compile(r"\bL1-\d{4}-\d{3}\b")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run retrieve-once over an evaluation question CSV."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Input CSV path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output CSV path.")
    parser.add_argument(
        "--context-dir",
        default=str(DEFAULT_CONTEXT_DIR),
        help="Directory for per-question retrieved context text files.",
    )
    parser.add_argument("--model", default=MODEL_NAME, help=f"Gemini model. Default: {MODEL_NAME}")
    parser.add_argument(
        "--max-context-chars",
        type=int,
        default=MAX_RECALL_CONTEXT_CHARS,
        help=f"Maximum retrieved context characters. Default: {MAX_RECALL_CONTEXT_CHARS}",
    )
    parser.add_argument(
        "--transcript-context-chars",
        type=int,
        default=0,
        help=(
            "Maximum full-transcript baseline context characters. "
            "Use 0 to avoid local truncation and let the model context window be the limit."
        ),
    )
    parser.add_argument("--limit", type=int, default=0, help="Run only the first N rows.")
    parser.add_argument(
        "--ids",
        default="",
        help="Comma-separated question ids to run, e.g. VM-E03,VM-E07.",
    )
    parser.add_argument(
        "--methods",
        default="structured,rag,transcript",
        help=(
            "Comma-separated methods to run: structured, rag, transcript. "
            "Default runs all three."
        ),
    )
    parser.add_argument(
        "--rag-mode",
        choices=("embedding", "lexical"),
        default="embedding",
        help="Raw transcript RAG retrieval mode. Default: embedding.",
    )
    return parser


def extract_actual_route(memory_context: str) -> str:
    for line in str(memory_context or "").splitlines():
        if line.startswith("strategy:"):
            return line.split(":", 1)[1].strip()
    return ""


def extract_l1_ids(memory_context: str) -> str:
    ids = sorted(set(L1_RE.findall(str(memory_context or ""))))
    return ", ".join(ids)


def load_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def write_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def select_rows(rows: list[dict[str, str]], *, ids: set[str], limit: int) -> list[dict[str, str]]:
    selected = [row for row in rows if not ids or row.get("question_id", "") in ids]
    if limit > 0:
        return selected[:limit]
    return selected


def parse_methods(value: str) -> set[str]:
    methods = {part.strip().lower() for part in str(value or "").split(",") if part.strip()}
    allowed = {"structured", "rag", "transcript"}
    unknown = methods - allowed
    if unknown:
        raise ValueError(f"Unsupported evaluation method(s): {', '.join(sorted(unknown))}")
    return methods or set(allowed)


def run_batch(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)
    output_path = Path(args.output)
    context_dir = Path(args.context_dir)
    rows, fieldnames = load_rows(input_path)
    for field in (
        "actual_route",
        "retrieved_l1_obj_ids",
        "agent_answer",
        "memory_context_path",
        "baseline_rag_answer",
        "baseline_rag_context_path",
        "baseline_transcript_answer",
        "baseline_transcript_context_path",
        "hallucination_flag",
    ):
        if field not in fieldnames:
            fieldnames.append(field)

    target_ids = {part.strip() for part in args.ids.split(",") if part.strip()}
    methods = parse_methods(args.methods)
    selected = select_rows(rows, ids=target_ids, limit=int(args.limit or 0))
    api_keys = resolve_api_keys()
    retrieval_api_key: Any = api_keys if len(api_keys) > 1 else (api_keys[0] if api_keys else None)

    context_dir.mkdir(parents=True, exist_ok=True)
    selected_ids = {id(row) for row in selected}
    for row in rows:
        if id(row) not in selected_ids:
            continue
        qid = row.get("question_id", "").strip() or "unknown"
        question = row.get("question", "").strip()
        if not question:
            continue
        if "structured" in methods:
            memory_context = retrieve_memory_context(
                query=question,
                api_key=retrieval_api_key,
                model_name=args.model,
                max_context_chars=max(500, int(args.max_context_chars)),
            )
            context_path = context_dir / f"{qid}_structured.txt"
            context_path.write_text(memory_context, encoding="utf-8")
            row["actual_route"] = extract_actual_route(memory_context)
            row["retrieved_l1_obj_ids"] = extract_l1_ids(memory_context)
            row["memory_context_path"] = str(context_path)
            if has_sufficient_memory_context(memory_context):
                row["agent_answer"] = generate_answer(
                    query=question,
                    memory_context=memory_context,
                    api_key=retrieval_api_key,
                    model_name=args.model,
                )
                row["hallucination_flag"] = ""
            else:
                row["agent_answer"] = INSUFFICIENT_MEMORY_ANSWER
                row["hallucination_flag"] = "insufficient_memory_gate"

        if "rag" in methods:
            rag_context = retrieve_plain_rag_context(
                query=question,
                api_key=retrieval_api_key,
                max_context_chars=max(500, int(args.max_context_chars)),
                mode=args.rag_mode,
            )
            rag_context_path = context_dir / f"{qid}_rag.txt"
            rag_context_path.write_text(rag_context, encoding="utf-8")
            row["baseline_rag_context_path"] = str(rag_context_path)
            row["baseline_rag_answer"] = generate_baseline_answer(
                query=question,
                context=rag_context,
                baseline_name=f"{args.rag_mode} raw transcript RAG",
                api_key=retrieval_api_key,
                model_name=args.model,
            )

        if "transcript" in methods:
            transcript_context = retrieve_full_transcript_context(
                row.get("gold_meeting_ids", ""),
                max_context_chars=max(0, int(args.transcript_context_chars)),
            )
            transcript_context_path = context_dir / f"{qid}_full_transcript.txt"
            transcript_context_path.write_text(transcript_context, encoding="utf-8")
            row["baseline_transcript_context_path"] = str(transcript_context_path)
            row["baseline_transcript_answer"] = generate_baseline_answer(
                query=question,
                context=transcript_context,
                baseline_name="oracle gold-meeting full transcript",
                api_key=retrieval_api_key,
                model_name=args.model,
            )

        print(
            f"{qid}: route={row.get('actual_route', '')} "
            f"structured={row.get('agent_answer', '')[:40]} "
            f"rag={row.get('baseline_rag_answer', '')[:40]} "
            f"transcript={row.get('baseline_transcript_answer', '')[:40]}"
        )

    write_rows(output_path, rows, fieldnames)
    print(f"wrote {output_path}")
    return 0


def main() -> None:
    raise SystemExit(run_batch())


if __name__ == "__main__":
    main()
