from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .data_loader import REPO_ROOT, ObservatoryDataLoader
from .datasets import resolve_dataset
from .retrieval_trace import RetrievalTraceService


ICSI_DEMO_QUERY = (
    "What context about delay-and-sum beamforming and close microphones "
    "should carry over to later audio processing discussions?"
)


@dataclass(frozen=True)
class DemoHealthCheck:
    name: str
    status: str
    detail: str
    value: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _status(checks: list[DemoHealthCheck]) -> str:
    statuses = {check.status for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def _path_check(name: str, path: Path, *, required: bool = True) -> DemoHealthCheck:
    exists = path.exists()
    if exists:
        return DemoHealthCheck(name=name, status="pass", detail=str(path), value=True)
    return DemoHealthCheck(
        name=name,
        status="fail" if required else "warn",
        detail=f"Missing: {path}",
        value=False,
    )


def _trace_check(name: str, count: int, detail: str, *, required: bool = True) -> DemoHealthCheck:
    if count > 0:
        return DemoHealthCheck(name=name, status="pass", detail=detail, value=count)
    return DemoHealthCheck(
        name=name,
        status="fail" if required else "warn",
        detail=detail,
        value=count,
    )


def _demo_query(dataset_id: str) -> str:
    if dataset_id == "icsi":
        return ICSI_DEMO_QUERY
    return "How does layered memory retrieval work?"


def _resolved_backend(dataset_id: str) -> str:
    if dataset_id == "icsi":
        return "optimization_v2_artifact"
    return "canonical"


def build_demo_health(repo_root: Path | str = REPO_ROOT, dataset_id: str = "icsi") -> dict[str, Any]:
    root = Path(repo_root)
    dataset = resolve_dataset(root, dataset_id)
    loader = ObservatoryDataLoader(root, dataset_id=dataset.dataset_id)
    checks: list[DemoHealthCheck] = [
        DemoHealthCheck(
            name="dataset_registered",
            status="pass",
            detail=dataset.label,
            value=dataset.dataset_id,
        ),
        _path_check("share_mem_root_exists", loader.share_mem_root),
        _path_check("l2_view_exists", dataset.l2_root / "l2_view.json"),
        _path_check("l3_view_exists", dataset.l3_root / "l3_view.json", required=False),
    ]

    query = _demo_query(dataset.dataset_id)
    trace: dict[str, Any] = {}
    trace_error = ""
    try:
        trace = RetrievalTraceService(root, dataset_id=dataset.dataset_id).run_trace(
            query=query,
            retrieval_mode="lexical",
            no_llm=True,
            include_debug=False,
            budget_profile="observatory_paper_trace",
            max_context_chars=0,
        )
    except Exception as exc:  # pragma: no cover - defensive, surfaced in health JSON.
        trace_error = f"{type(exc).__name__}: {exc}"

    if trace_error:
        checks.append(DemoHealthCheck("demo_trace_runs", "fail", trace_error, False))
    else:
        metrics = trace.get("metrics", {}) if isinstance(trace.get("metrics"), dict) else {}
        l1_count = int(metrics.get("selected_l1_count") or len(trace.get("l1_evidence_seeds") or []))
        l2_count = int(metrics.get("selected_l2_count") or len(trace.get("l2_evolution_context") or []))
        l3_count = int(metrics.get("selected_l3_count") or len(trace.get("l3_navigation") or []))
        prompt_context = str(trace.get("formatted_prompt_context") or "")
        checks.extend(
            [
                DemoHealthCheck("demo_trace_runs", "pass", "Retrieval trace completed.", True),
                _trace_check("demo_trace_has_l1", l1_count, "Trace selected at least one L1 evidence seed."),
                _trace_check("demo_trace_has_l2", l2_count, "Trace selected at least one L2 topic context."),
                _trace_check(
                    "demo_trace_has_l3",
                    l3_count,
                    "Trace selected at least one L3 navigation family.",
                    required=False,
                ),
                _trace_check(
                    "demo_trace_has_prompt",
                    len(prompt_context.strip()),
                    "Trace produced formatted prompt context.",
                ),
            ]
        )

    return {
        "dataset": dataset.dataset_id,
        "dataset_label": dataset.label,
        "status": _status(checks),
        "resolved_backend": _resolved_backend(dataset.dataset_id),
        "query": query,
        "checks": [check.to_dict() for check in checks],
        "trace_summary": {
            "l1_count": len(trace.get("l1_evidence_seeds") or []),
            "l2_count": len(trace.get("l2_evolution_context") or []),
            "l3_count": len(trace.get("l3_navigation") or []),
            "prompt_chars": len(str(trace.get("formatted_prompt_context") or "")),
        },
    }
