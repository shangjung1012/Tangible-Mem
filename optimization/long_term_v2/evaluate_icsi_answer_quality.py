from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import load_json, utc_now_iso, write_json, write_text


def _retrieval_report(run_root: Path) -> dict[str, Any]:
    return load_json(run_root / "retrieval_eval_icsi_effective" / "retrieval_eval_report.json")


def _avg_selected_l1(report: dict[str, Any]) -> float:
    counts = [len(row.get("selected_l1", []) or []) for row in report.get("queries", []) or []]
    return round(sum(counts) / len(counts), 3) if counts else 0.0


def _strategy_summary(name: str, run_root: Path) -> dict[str, Any]:
    report = _retrieval_report(run_root)
    summary = report.get("summary", {}) or {}
    recall = float(summary.get("avg_expected_obj_recall_at_context", 0.0) or 0.0)
    semantic_l2 = float(summary.get("expected_l2_semantic_hit_rate", 0.0) or 0.0)
    semantic_l3 = float(summary.get("expected_l3_semantic_hit_rate", 0.0) or 0.0)
    traceability = min(1.0, _avg_selected_l1(report) / max(float(summary.get("top_k_l1", 60) or 60), 1.0))
    grounding = min(1.0, (recall * 0.7) + (semantic_l2 * 0.2) + (semantic_l3 * 0.1))
    topic_evolution = min(1.0, (semantic_l2 * 0.55) + (semantic_l3 * 0.45))
    hallucination_safety = min(1.0, 0.5 + grounding * 0.5)
    overall = round(
        grounding * 0.36
        + topic_evolution * 0.24
        + traceability * 0.20
        + hallucination_safety * 0.20,
        4,
    )
    return {
        "strategy": name,
        "run_root": str(run_root.resolve()),
        "proxy_overall_score": overall,
        "dimensions": {
            "evidence_grounding": round(grounding, 4),
            "topic_evolution": round(topic_evolution, 4),
            "source_traceability": round(traceability, 4),
            "hallucination_safety": round(hallucination_safety, 4),
        },
        "retrieval_summary": summary,
    }


def evaluate_icsi_answer_quality_proxy(
    *,
    baseline_run_root: Path | str,
    candidate_run_root: Path | str,
    out: Path | str | None = None,
) -> dict[str, Any]:
    baseline_root = Path(baseline_run_root)
    candidate_root = Path(candidate_run_root)
    baseline = _strategy_summary(baseline_root.name, baseline_root)
    candidate = _strategy_summary(candidate_root.name, candidate_root)
    decision = "candidate_not_worse" if candidate["proxy_overall_score"] >= baseline["proxy_overall_score"] else "candidate_regressed"
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "method": "no_llm_retrieval_quality_proxy",
        "strategy_count": 2,
        "strategies": {
            baseline["strategy"]: baseline,
            candidate["strategy"]: candidate,
        },
        "score_delta": round(candidate["proxy_overall_score"] - baseline["proxy_overall_score"], 4),
        "decision": decision,
        "limitations": [
            "This is not final answer scoring; it estimates answer quality from retrieval recall, semantic topic hits, and source traceability.",
            "Full-context and RAG answer quality still require the Memory Observatory or LLM answer scorer for a final claim.",
        ],
    }
    if out is not None:
        out_dir = Path(out)
        write_json(out_dir / "icsi_answer_quality_proxy.json", report)
        write_text(out_dir / "icsi_answer_quality_proxy.md", _format_md(report))
    return report


def _format_md(report: dict[str, Any]) -> str:
    lines = [
        "# ICSI Answer Quality Proxy",
        "",
        f"- method: `{report['method']}`",
        f"- decision: `{report['decision']}`",
        f"- score delta: `{report['score_delta']}`",
        "",
        "| Strategy | Proxy Overall | Evidence Grounding | Topic Evolution | Source Traceability |",
        "|---|---:|---:|---:|---:|",
    ]
    for strategy, row in report["strategies"].items():
        dimensions = row["dimensions"]
        lines.append(
            f"| {strategy} | {row['proxy_overall_score']} | {dimensions['evidence_grounding']} | "
            f"{dimensions['topic_evolution']} | {dimensions['source_traceability']} |"
        )
    lines.extend(["", "## Limitations", ""])
    for item in report["limitations"]:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ICSI candidate answer quality using a no-LLM retrieval-quality proxy.")
    parser.add_argument("--baseline-run-root", required=True)
    parser.add_argument("--candidate-run-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = evaluate_icsi_answer_quality_proxy(
        baseline_run_root=args.baseline_run_root,
        candidate_run_root=args.candidate_run_root,
        out=args.out,
    )
    print(f"[optimization:v2] ICSI answer-quality proxy complete: decision={report['decision']} delta={report['score_delta']}")


if __name__ == "__main__":
    main()
