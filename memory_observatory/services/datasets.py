from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DatasetConfig:
    dataset_id: str
    label: str
    description: str
    share_mem_root: Path
    l2_root: Path
    l3_root: Path
    runs_root: Path
    l2_validation_path: Path
    l3_validation_path: Path
    retrieval_eval_report_path: Path
    system_comparison_path: Path | None = None
    topic_surface_ablation_path: Path | None = None
    read_only: bool = False

    def public_metadata(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "label": self.label,
            "description": self.description,
            "read_only": self.read_only,
        }


def dataset_configs(repo_root: Path | str) -> dict[str, DatasetConfig]:
    root = Path(repo_root)
    icsi_run = root / "optimization" / "runs" / "icsi_bmr_full_completed29_v2_20260614"
    return {
        "grace": DatasetConfig(
            dataset_id="grace",
            label="Grace",
            description="Internal mentor-mentee project meetings.",
            share_mem_root=root / "share_mem",
            l2_root=root / "long_term" / "l2",
            l3_root=root / "long_term" / "l3",
            runs_root=root / "memory_observatory" / "runs",
            l2_validation_path=root / "long_term" / "l2" / "validation" / "l2_validation_report.json",
            l3_validation_path=root / "long_term" / "l3" / "validation" / "l3_validation_report.json",
            retrieval_eval_report_path=root / "long_term" / "eval" / "retrieval_eval_report.json",
            read_only=False,
        ),
        "icsi": DatasetConfig(
            dataset_id="icsi",
            label="ICSI",
            description="ICSI BMR large-corpus evidence-grounded held-out evaluation.",
            share_mem_root=root
            / "optimization"
            / "reports"
            / "icsi_bmr_full_completed29_eval_pack_20260614"
            / "source_share_mem",
            l2_root=icsi_run / "runtime" / "l2",
            l3_root=icsi_run / "runtime" / "l3",
            runs_root=root / "memory_observatory" / "runs",
            l2_validation_path=icsi_run / "validation" / "l2_validation_report.json",
            l3_validation_path=icsi_run / "validation" / "l3_validation_report.json",
            retrieval_eval_report_path=root
            / "optimization"
            / "reports"
            / "icsi_bmr_full_completed29_system_comparison_revised_20260614"
            / "retrieval_eval_revised_report.json",
            system_comparison_path=root
            / "optimization"
            / "reports"
            / "icsi_bmr_full_completed29_system_comparison_revised_20260614"
            / "system_comparison_summary.json",
            topic_surface_ablation_path=root
            / "optimization"
            / "reports"
            / "icsi_bmr_full_completed29_l2_l3_ablation_20260614"
            / "icsi_l2_l3_ablation_no_llm.json",
            read_only=True,
        ),
    }


def resolve_dataset(repo_root: Path | str, dataset_id: str | None = None) -> DatasetConfig:
    configs = dataset_configs(repo_root)
    key = (dataset_id or "grace").strip().lower()
    if key not in configs:
        raise KeyError(key)
    return configs[key]


def list_datasets(repo_root: Path | str) -> list[dict[str, Any]]:
    return [config.public_metadata() for config in dataset_configs(repo_root).values()]
