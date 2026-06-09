from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import memory_context
from optimization.long_term_v2.io_utils import load_json, utc_now_iso, write_json, write_text


REQUIRED_RUNTIME_RELATIVE_PATHS = [
    "runtime/input_snapshot/tree.json",
    "runtime/l2/l2_index.json",
    "runtime/l2/l2_view.json",
    "runtime/l2/l2_secondary_links.json",
    "runtime/l3/l3_promotions.json",
    "runtime/l3/l3_view.json",
    "runtime/l3/l3_index.json",
]


def _load_jsonl(path: Path | str) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in source.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _path_dict(paths: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in paths.items():
        output[key] = str(value) if isinstance(value, Path) else value
    return output


@contextmanager
def _temporary_env(updates: dict[str, str], removals: list[str] | None = None) -> Iterator[None]:
    removals = removals or []
    touched = set(updates) | set(removals)
    previous = {key: os.environ.get(key) for key in touched}
    try:
        for key in removals:
            os.environ.pop(key, None)
        for key, value in updates.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def inspect_runtime_export(run_root: Path | str) -> dict[str, Any]:
    root = Path(run_root)
    missing = [
        relative
        for relative in REQUIRED_RUNTIME_RELATIVE_PATHS
        if not (root / relative).exists()
    ]
    manifest_path = root / "runtime" / "manifest.json"
    manifest = load_json(manifest_path) if manifest_path.exists() else {}
    return {
        "run_root": str(root.resolve()),
        "runtime_root": str((root / "runtime").resolve()),
        "required_runtime_files": REQUIRED_RUNTIME_RELATIVE_PATHS,
        "missing_runtime_files": missing,
        "missing_runtime_file_count": len(missing),
        "runtime_manifest_exists": manifest_path.exists(),
        "runtime_manifest": manifest,
    }


def _resolver_report(run_root: Path, *, optimization_enabled: bool) -> dict[str, Any]:
    if optimization_enabled:
        updates = {
            "LONG_TERM_BACKEND": "optimization_v2",
            "OPTIMIZATION_V2_RUN_ROOT": str(run_root),
        }
        removals = ["OPTIMIZATION_V2_RUNTIME_ROOT"]
    else:
        updates = {}
        removals = [
            "LONG_TERM_BACKEND",
            "OPTIMIZATION_V2_RUN_ROOT",
            "OPTIMIZATION_V2_RUNTIME_ROOT",
        ]
    with _temporary_env(updates, removals):
        return _path_dict(memory_context.resolve_long_term_runtime_paths())


def _sample_traces(run_root: Path, queries_path: Path, max_queries: int) -> list[dict[str, Any]]:
    rows = _load_jsonl(queries_path)[: max(0, max_queries)]
    traces: list[dict[str, Any]] = []
    with _temporary_env(
        {
            "LONG_TERM_BACKEND": "optimization_v2",
            "OPTIMIZATION_V2_RUN_ROOT": str(run_root),
        },
        ["OPTIMIZATION_V2_RUNTIME_ROOT"],
    ):
        for index, row in enumerate(rows, start=1):
            query = str(row.get("query") or row.get("question") or "").strip()
            query_id = str(row.get("query_id") or row.get("question_id") or f"q{index:03d}")
            if not query:
                continue
            try:
                context = memory_context.retrieve_long_term_context(
                    query=query,
                    api_key="",
                    model_name="gemini-2.5-pro",
                    max_context_chars=16000,
                    use_llm_planner=False,
                    retrieval_mode="lexical",
                )
                traces.append(
                    {
                        "query_id": query_id,
                        "query": query,
                        "status": "ok",
                        "context_char_count": len(context),
                        "has_global_topic_map": "Global Topic Map" in context,
                        "has_l1_evidence_seeds": "L1 Evidence Seeds" in context,
                        "has_l2_evolution_context": "L2 / Child-L2 Evolution Context" in context,
                        "context_preview": context[:2400],
                    }
                )
            except Exception as exc:  # pragma: no cover - kept visible in generated report.
                traces.append(
                    {
                        "query_id": query_id,
                        "query": query,
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
    return traces


def _decision(report: dict[str, Any]) -> str:
    if report["missing_runtime_file_count"] > 0:
        return "not_ready"
    if report["optimization_resolver"].get("backend") != "optimization_v2":
        return "not_ready"
    traces = report.get("sample_traces", [])
    if not traces:
        return "not_ready"
    if any(trace.get("status") != "ok" for trace in traces):
        return "not_ready"
    if not all(
        trace.get("has_global_topic_map") and trace.get("has_l1_evidence_seeds")
        for trace in traces
    ):
        return "not_ready"
    return "shadow_ready"


def _write_markdown(report: dict[str, Any], out: Path) -> None:
    manifest = report.get("runtime_manifest", {})
    lines = [
        "# Optimization V2 Shadow Runtime Readiness",
        "",
        f"- decision: `{report['decision']}`",
        f"- source run root: `{report['run_root']}`",
        f"- runtime root: `{report['runtime_root']}`",
        f"- missing runtime files: `{report['missing_runtime_file_count']}`",
        f"- optimization resolver backend: `{report['optimization_resolver'].get('backend')}`",
        f"- fallback resolver backend: `{report['fallback_resolver'].get('backend')}`",
        f"- canonical mutation: `{str(report['canonical_mutation']).lower()}`",
        f"- L2 topics: `{manifest.get('l2_topic_count', 0)}`",
        f"- L3 parents: `{manifest.get('l3_parent_count', 0)}`",
        f"- L2 index count: `{manifest.get('l2_index_count', 0)}`",
        f"- L3 index count: `{manifest.get('l3_index_count', 0)}`",
        "",
        "## Sample Traces",
        "",
    ]
    for trace in report.get("sample_traces", []):
        lines.extend(
            [
                f"### {trace.get('query_id')}",
                "",
                f"- status: `{trace.get('status')}`",
                f"- context chars: `{trace.get('context_char_count', 0)}`",
                f"- has Global Topic Map: `{trace.get('has_global_topic_map', False)}`",
                f"- has L1 Evidence Seeds: `{trace.get('has_l1_evidence_seeds', False)}`",
                f"- has L2 Evolution Context: `{trace.get('has_l2_evolution_context', False)}`",
                f"- query: {trace.get('query', '')}",
                "",
            ]
        )
    if report.get("missing_runtime_files"):
        lines.extend(["## Missing Runtime Files", ""])
        lines.extend(f"- `{path}`" for path in report["missing_runtime_files"])
        lines.append("")
    lines.extend(
        [
            "## Boundary",
            "",
            "- This is a read-only shadow readiness report.",
            "- It does not change `.env`, canonical `share_mem/`, or canonical `long_term/` artifacts.",
            "- `shadow_ready` means the candidate can be tested through the runtime resolver; it does not mean canonical promotion.",
        ]
    )
    write_text(out / "summary.md", "\n".join(lines) + "\n")


def run_shadow_readiness_report(
    *,
    run_root: Path | str,
    queries_path: Path | str,
    out: Path | str,
    max_queries: int = 3,
) -> dict[str, Any]:
    root = Path(run_root)
    output_root = Path(out)
    output_root.mkdir(parents=True, exist_ok=True)

    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        **inspect_runtime_export(root),
        "optimization_resolver": _resolver_report(root, optimization_enabled=True),
        "fallback_resolver": _resolver_report(root, optimization_enabled=False),
        "sample_traces": [],
        "canonical_mutation": False,
        "promotion_boundary": "shadow_ready_is_not_canonical_promotion",
    }
    if report["missing_runtime_file_count"] == 0:
        report["sample_traces"] = _sample_traces(root, Path(queries_path), max_queries)
    report["decision"] = _decision(report)

    write_json(output_root / "summary.json", report)
    _write_markdown(report, output_root)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify an isolated optimization v2 run can be used in read-only shadow runtime mode."
    )
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-queries", type=int, default=3)
    args = parser.parse_args()

    report = run_shadow_readiness_report(
        run_root=args.run_root,
        queries_path=args.queries,
        out=args.out,
        max_queries=args.max_queries,
    )
    print(
        "[optimization:v2] shadow readiness complete: "
        f"decision={report['decision']} missing={report['missing_runtime_file_count']} "
        f"samples={len(report['sample_traces'])}"
    )


if __name__ == "__main__":
    main()
