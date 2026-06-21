from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .services.data_loader import ObservatoryDataLoader, REPO_ROOT
from .services.datasets import list_datasets, resolve_dataset
from .services.demo_health import build_demo_health
from .services.experiment_runner import run_experiment
from .services.feedback_store import FeedbackStore
from .services.memory_store import MemoryStore
from .services.report_store import ReportStore
from .services.retrieval_trace import RetrievalTraceService
from .services.topic_store import TopicStore

STATIC_DIR = Path(__file__).resolve().parent / "static"
RUNS_DIR = Path(__file__).resolve().parent / "runs"


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round_metric(value: Any, digits: int = 4) -> float:
    return round(_as_float(value), digits)


def _format_k_tokens(value: Any) -> str:
    number = _as_float(value)
    if number >= 100_000:
        return f"{number / 1000:.0f}k"
    if number >= 1000:
        return f"{number / 1000:.1f}k"
    return str(int(round(number)))


def _evaluation_summary(loader: ObservatoryDataLoader) -> dict[str, Any]:
    comparison = loader.load_system_comparison_summary()
    summary = comparison.get("summary", {}) if isinstance(comparison.get("summary"), dict) else {}
    if not summary:
        return {}
    recalls = summary.get("expected_l1_recall", {}) if isinstance(summary.get("expected_l1_recall"), dict) else {}
    tokens = summary.get("avg_context_tokens", {}) if isinstance(summary.get("avg_context_tokens"), dict) else {}
    full_tokens = _as_float(tokens.get("full_context_l1") or tokens.get("full_context"))
    layered_tokens = _as_float(tokens.get("optimization_v2_layered") or tokens.get("layered_memory"))
    full_recall = _round_metric(recalls.get("full_context_l1") or recalls.get("full_context"), 4)
    rag_recall = _round_metric(recalls.get("rag_l1_lexical") or recalls.get("rag_baseline"), 4)
    layered_recall = _round_metric(recalls.get("optimization_v2_layered") or recalls.get("layered_memory"), 4)
    rag_tokens = _round_metric(tokens.get("rag_l1_lexical") or tokens.get("rag_baseline"), 2)
    return {
        "query_count": int(summary.get("query_count", 0) or 0),
        "full_context_recall": full_recall,
        "rag_recall": rag_recall,
        "layered_recall": layered_recall,
        "full_context_tokens": _round_metric(full_tokens, 2),
        "rag_tokens": rag_tokens,
        "layered_tokens": _round_metric(layered_tokens, 2),
        "full_context": {
            "label": "Full Context",
            "recall": full_recall,
            "tokens": _round_metric(full_tokens, 2),
            "tokens_label": _format_k_tokens(full_tokens),
        },
        "rag": {
            "label": "RAG top-20",
            "recall": rag_recall,
            "tokens": rag_tokens,
            "tokens_label": _format_k_tokens(tokens.get("rag_l1_lexical") or tokens.get("rag_baseline")),
        },
        "layered": {
            "label": "Layered Memory",
            "recall": layered_recall,
            "tokens": _round_metric(layered_tokens, 2),
            "tokens_label": _format_k_tokens(layered_tokens),
        },
        "layered_full_context_token_pct": _round_metric((layered_tokens / full_tokens) * 100 if full_tokens else 0, 2),
        "example_query": (comparison.get("queries") or [{}])[0] if isinstance(comparison.get("queries"), list) else {},
    }


def _topic_surface_summary(loader: ObservatoryDataLoader) -> dict[str, Any]:
    ablation = loader.load_topic_surface_ablation()
    summary = ablation.get("summary", {}) if isinstance(ablation.get("summary"), dict) else {}
    if not summary:
        return {}
    l2_hit = summary.get("avg_context_visible_l2_hit", {})
    l3_hit = summary.get("avg_context_visible_l3_hit", {})
    l2_hit_value = l2_hit.get("l1_plus_l2_l3_surface") if isinstance(l2_hit, dict) else l2_hit
    l3_hit_value = l3_hit.get("l1_plus_l2_l3_surface") if isinstance(l3_hit, dict) else l3_hit
    return {
        "extra_tokens": _round_metric(summary.get("avg_token_delta_l2_l3"), 2),
        "l2_hit": _round_metric(l2_hit_value, 4),
        "l3_hit": _round_metric(l3_hit_value, 4),
    }


def _overview(repo_root: Path, dataset_id: str = "grace") -> dict[str, Any]:
    loader = ObservatoryDataLoader(repo_root, dataset_id=dataset_id)
    dataset_config = loader.dataset
    tree = loader.load_share_tree()
    meetings = loader.iter_meetings()
    l1_count = len(loader.iter_l1_objects())
    l2_view = loader.load_l2_view()
    l2_index = loader.load_l2_index()
    l3_view = loader.load_l3_view()
    l3_index = loader.load_l3_index()
    l3_validation = loader.load_l3_validation()
    l2_validation = loader.load_l2_validation()
    eval_report = loader.load_retrieval_eval_report()
    child_count = sum(len(node.get("child_l2_nodes", []) or []) for node in l3_view.get("l3_nodes", []) or [])
    coverage = l3_validation.get("promotion_coverage", {}) if isinstance(l3_validation.get("promotion_coverage"), dict) else {}
    return {
        "dataset_id": dataset_config.dataset_id,
        "dataset_label": dataset_config.label,
        "dataset_description": dataset_config.description,
        "dataset_read_only": dataset_config.read_only,
        "tree_version": tree.get("tree_version"),
        "meeting_count": len(meetings),
        "l1_object_count": l1_count,
        "l2_topic_count": len(l2_view.get("l2_nodes", []) or []),
        "linked_l1_count": len(l2_index),
        "unlinked_l1_count": max(0, l1_count - len(l2_index)),
        "materialized_l3_count": int(l3_view.get("materialized_l3_count", len(l3_view.get("l3_nodes", []) or [])) or 0),
        "child_l2_count": child_count,
        "l3_assigned_l1_count": len(l3_index),
        "l3_unassigned_l1_count": int(coverage.get("unassigned_l1_count", 0) or 0),
        "duplicate_assignment_count": int(coverage.get("duplicate_assignment_count", 0) or 0),
        "invalid_l3_index_count": int(coverage.get("invalid_l3_index_count", 0) or 0),
        "retrieval_eval_query_count": int(eval_report.get("query_count", 0) or 0),
        "retrieval_eval_run_count": int(eval_report.get("run_count", 0) or 0),
        "l2_validation": {
            "severe_count": l2_validation.get("severe_count", l2_validation.get("severe_issue_count", 0)),
            "warning_count": l2_validation.get("warning_count", 0),
        },
        "l3_validation": {
            "severe_count": l3_validation.get("severe_count", 0),
            "warning_count": l3_validation.get("warning_count", 0),
        },
        "evaluation_summary": _evaluation_summary(loader),
        "topic_surface_summary": _topic_surface_summary(loader),
    }


def create_app(repo_root: Path | str = REPO_ROOT) -> FastAPI:
    root = Path(repo_root)
    app = FastAPI(title="Memory Observatory", version="0.1.0")
    app.state.repo_root = root
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def dataset_or_404(dataset_id: str) -> str:
        try:
            return resolve_dataset(root, dataset_id).dataset_id
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown dataset: {dataset_id}") from exc

    def loader(dataset_id: str = "grace") -> ObservatoryDataLoader:
        return ObservatoryDataLoader(root, dataset_id=dataset_or_404(dataset_id))

    def memory_store(dataset_id: str = "grace") -> MemoryStore:
        return MemoryStore(root, dataset_id=dataset_or_404(dataset_id))

    def topic_store(dataset_id: str = "grace") -> TopicStore:
        return TopicStore(root, dataset_id=dataset_or_404(dataset_id))

    def feedback_store() -> FeedbackStore:
        return FeedbackStore(loader().share_mem_root)

    def report_store() -> ReportStore:
        return ReportStore(RUNS_DIR if root == REPO_ROOT else root / "memory_observatory" / "runs")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/datasets")
    def api_datasets() -> list[dict[str, Any]]:
        return list_datasets(root)

    @app.get("/api/overview")
    def api_overview(dataset: str = "grace") -> dict[str, Any]:
        dataset_id = dataset_or_404(dataset)
        return _overview(root, dataset_id=dataset_id)

    @app.get("/api/demo/health")
    def api_demo_health(dataset: str = "icsi") -> dict[str, Any]:
        dataset_id = dataset_or_404(dataset)
        return build_demo_health(root, dataset_id=dataset_id)

    @app.get("/api/meetings")
    def api_meetings(dataset: str = "grace") -> list[dict[str, Any]]:
        return memory_store(dataset).meetings()

    @app.get("/api/meetings/{meeting_id}/objects")
    def api_meeting_objects(meeting_id: str, dataset: str = "grace") -> list[dict[str, Any]]:
        return memory_store(dataset).objects(meeting_id=meeting_id)

    @app.get("/api/objects")
    def api_objects(meeting_id: str | None = None, dataset: str = "grace") -> list[dict[str, Any]]:
        return memory_store(dataset).objects(meeting_id=meeting_id)

    @app.get("/api/objects/{obj_id}")
    def api_object(obj_id: str, dataset: str = "grace") -> dict[str, Any]:
        detail = memory_store(dataset).object_detail(obj_id)
        if not detail:
            raise HTTPException(status_code=404, detail="object not found")
        return detail

    @app.get("/api/topics/l2")
    def api_l2_topics(dataset: str = "grace") -> list[dict[str, Any]]:
        return topic_store(dataset).l2_nodes()

    @app.get("/api/topics/l2/{l2_id}")
    def api_l2_topic(l2_id: str, dataset: str = "grace") -> dict[str, Any]:
        node = topic_store(dataset).get_l2(l2_id)
        if not node:
            raise HTTPException(status_code=404, detail="L2 not found")
        return node

    @app.get("/api/topics/l3")
    def api_l3_topics(dataset: str = "grace") -> dict[str, Any]:
        return topic_store(dataset).hierarchy()

    @app.get("/api/topics/l3/{l3_id}")
    def api_l3_topic(l3_id: str, dataset: str = "grace") -> dict[str, Any]:
        node = topic_store(dataset).get_l3(l3_id)
        if not node:
            raise HTTPException(status_code=404, detail="L3 not found")
        return node

    @app.get("/api/retrieval/trace")
    def api_retrieval_trace(
        query: str = Query(..., min_length=1),
        dataset: str = "grace",
        retrieval_mode: str = Query("hybrid", pattern="^(hybrid|lexical|semantic)$"),
        no_llm: bool = True,
        include_debug: bool = True,
        planner_model: str | None = None,
        budget_profile: str = "",
        max_context_chars: int = 16000,
    ) -> dict[str, Any]:
        dataset_id = dataset_or_404(dataset)
        return RetrievalTraceService(root, dataset_id=dataset_id).run_trace(
            query=query,
            retrieval_mode=retrieval_mode,
            no_llm=no_llm,
            include_debug=include_debug,
            planner_model_name=planner_model,
            budget_profile=budget_profile,
            max_context_chars=max_context_chars,
        )

    @app.get("/api/feedback/importance")
    def api_feedback_importance() -> list[dict[str, Any]]:
        return feedback_store().load_adjustments()

    @app.post("/api/feedback/importance")
    def api_save_feedback(payload: dict[str, Any]) -> dict[str, Any]:
        return feedback_store().save_importance_adjustment(payload)

    @app.get("/api/feedback/summary")
    def api_feedback_summary() -> dict[str, Any]:
        return feedback_store().load_summary()

    @app.get("/api/runs")
    def api_runs(include_legacy: bool = False) -> list[dict[str, Any]]:
        return report_store().list_runs(include_legacy=include_legacy)

    @app.get("/api/runs/{run_id}")
    def api_run(run_id: str) -> dict[str, Any]:
        data = report_store().load_run(run_id)
        if not data:
            raise HTTPException(status_code=404, detail="run not found")
        return data

    @app.get("/api/runs/{run_id}/summary")
    def api_run_summary(run_id: str) -> dict[str, Any]:
        data = report_store().load_run(run_id)
        if not data:
            raise HTTPException(status_code=404, detail="run not found")
        return data.get("summary", {})

    @app.get("/api/runs/{run_id}/queries")
    def api_run_queries(run_id: str) -> list[dict[str, Any]]:
        data = report_store().load_run(run_id)
        if not data:
            raise HTTPException(status_code=404, detail="run not found")
        return data.get("queries", [])

    @app.get("/api/runs/{run_id}/queries/{query_id}")
    def api_run_query(run_id: str, query_id: str) -> dict[str, Any]:
        data = report_store().load_query(run_id, query_id)
        if not data:
            raise HTTPException(status_code=404, detail="query not found")
        return data

    @app.get("/api/runs/{run_id}/queries/{query_id}/context/{strategy}")
    def api_run_context(run_id: str, query_id: str, strategy: str) -> PlainTextResponse:
        return PlainTextResponse(report_store().load_context(run_id, query_id, strategy))

    @app.get("/api/runs/{run_id}/queries/{query_id}/answer/{strategy}")
    def api_run_answer(run_id: str, query_id: str, strategy: str) -> PlainTextResponse:
        return PlainTextResponse(report_store().load_answer(run_id, query_id, strategy))

    @app.post("/api/runs")
    def api_create_run(payload: dict[str, Any]) -> dict[str, Any]:
        strategies = payload.get("strategies") or ["full_context", "rag_baseline", "layered_memory"]
        max_context_chars = payload.get("max_context_chars", 0)
        if max_context_chars is None:
            max_context_chars = 0
        result = run_experiment(
            repo_root=root,
            queries_path=payload.get("queries_path", "long_term/eval/long_term_retrieval_queries.jsonl"),
            out=report_store().runs_root,
            strategies=strategies,
            retrieval_mode=payload.get("retrieval_mode", "hybrid"),
            no_llm=bool(payload.get("no_llm", True)),
            generate_answers=bool(payload.get("generate_answers", False)),
            model=payload.get("model", "gemini-2.5-pro"),
            planner_model=payload.get("planner_model"),
            max_context_chars=int(max_context_chars),
            rag_top_k=int(payload.get("rag_top_k", 6) or 6),
            budget_profile=str(payload.get("budget_profile", "") or ""),
            full_context_scope=str(payload.get("full_context_scope", "all") or "all"),
            baseline_token_multiplier=float(payload.get("baseline_token_multiplier", 0.0) or 0.0),
            full_context_max_tokens=int(payload.get("full_context_max_tokens", 0) or 0),
            rag_max_context_tokens=int(payload.get("rag_max_context_tokens", 0) or 0),
        )
        return {"run_id": result["run_id"], "summary": result["summary"]}

    return app


app = create_app()
