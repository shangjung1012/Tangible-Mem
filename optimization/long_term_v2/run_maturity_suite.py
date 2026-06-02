from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.build_view import build_view
from optimization.long_term_v2.compare_with_baseline import compare_with_baseline
from optimization.long_term_v2.evaluate_retrieval import evaluate_retrieval
from optimization.long_term_v2.io_utils import ensure_optimization_output, utc_now_iso, write_json, write_text
from optimization.long_term_v2.maturity_certification import generate_manual_review_protocol
from optimization.long_term_v2.validate_view import validate_run


def load_datasets_config(path: Path | str) -> list[dict[str, Any]]:
    import json

    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("datasets JSON must contain a list of dataset configs")
    return data


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "dataset"


def _clean_suite_root(path: Path, *, clean: bool) -> Path:
    root = ensure_optimization_output(path)
    if clean and root.exists():
        shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
    return root


def run_maturity_suite(
    *,
    suite_root: Path | str,
    datasets: list[dict[str, Any]],
    clean: bool = False,
) -> dict[str, Any]:
    root = _clean_suite_root(Path(suite_root), clean=clean)
    dataset_reports: list[dict[str, Any]] = []
    for dataset in datasets:
        name = str(dataset.get("name", "") or dataset.get("dataset_id", "") or f"dataset-{len(dataset_reports)+1}")
        run_root = root / f"{_slug(name)}_deterministic"
        build = build_view(
            share_mem_root=dataset["share_mem_root"],
            profile_path=dataset["profile"],
            out_root=run_root,
            mode="deterministic",
            clean=True,
        )
        validation = validate_run(run_root=run_root)
        generate_manual_review_protocol(run_root=run_root, out_dir=run_root / "manual_review")
        comparison = None
        if dataset.get("baseline_l2_root") and dataset.get("baseline_l3_root"):
            comparison = compare_with_baseline(
                run_root=run_root,
                baseline_l2_root=dataset["baseline_l2_root"],
                baseline_l3_root=dataset["baseline_l3_root"],
                share_mem_root=dataset.get("comparison_share_mem_root", dataset["share_mem_root"]),
            )
        retrieval = None
        if dataset.get("queries"):
            retrieval = evaluate_retrieval(
                run_root=run_root,
                queries_path=dataset["queries"],
                share_mem_root=dataset.get("retrieval_share_mem_root", dataset["share_mem_root"]),
                out_subdir=dataset.get("retrieval_out_subdir", "retrieval_eval"),
            )
        dataset_reports.append(
            {
                "name": name,
                "run_root": str(run_root),
                "source_l1_count": build["manifest"]["source_l1_count"],
                "l2_topic_count": build["manifest"]["l2_topic_count"],
                "l3_parent_count": build["manifest"]["l3_parent_count"],
                "severe_count": validation["severe_count"],
                "warning_count": validation["warning_count"],
                "comparison": comparison,
                "retrieval_summary": retrieval.get("summary") if retrieval else None,
            }
        )
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "suite_root": str(root.resolve()),
        "dataset_count": len(dataset_reports),
        "datasets": dataset_reports,
        "status": "pass" if all(row["severe_count"] == 0 for row in dataset_reports) else "fail",
    }
    write_json(root / "suite_manifest.json", {"generated_at_utc": report["generated_at_utc"], "datasets": datasets})
    write_json(root / "suite_summary.json", report)
    lines = [
        "# Optimization v2 Maturity Suite",
        "",
        f"- status: `{report['status']}`",
        f"- datasets: {len(dataset_reports)}",
        "",
    ]
    for row in dataset_reports:
        lines.append(
            f"- {row['name']}: L1={row['source_l1_count']} L2={row['l2_topic_count']} "
            f"L3={row['l3_parent_count']} severe={row['severe_count']} warnings={row['warning_count']}"
        )
    write_text(root / "suite_summary.md", "\n".join(lines) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run isolated optimization v2 maturity suite datasets.")
    parser.add_argument("--suite-root", required=True)
    parser.add_argument("--datasets-json", required=True, help="JSON file containing a list of dataset configs.")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    datasets = load_datasets_config(args.datasets_json)
    report = run_maturity_suite(suite_root=args.suite_root, datasets=datasets, clean=args.clean)
    print(f"[optimization:v2] maturity suite complete: status={report['status']} datasets={report['dataset_count']}")


if __name__ == "__main__":
    main()
