from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .services.data_loader import ObservatoryDataLoader, REPO_ROOT
from .services.experiment_runner import run_experiment
from .services.feedback_store import FeedbackStore
from .services.memory_store import MemoryStore
from .services.report_store import ReportStore
from .services.retrieval_trace import RetrievalTraceService
from .services.topic_store import TopicStore

STATIC_DIR = Path(__file__).resolve().parent / "static"
RUNS_DIR = Path(__file__).resolve().parent / "runs"


def _overview(repo_root: Path) -> dict[str, Any]:
    loader = ObservatoryDataLoader(repo_root)
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
    }


def create_app(repo_root: Path | str = REPO_ROOT) -> FastAPI:
    root = Path(repo_root)
    app = FastAPI(title="Memory Observatory", version="0.1.0")
    app.state.repo_root = root
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def loader() -> ObservatoryDataLoader:
        return ObservatoryDataLoader(root)

    def memory_store() -> MemoryStore:
        return MemoryStore(root)

    def topic_store() -> TopicStore:
        return TopicStore(root)

    def feedback_store() -> FeedbackStore:
        return FeedbackStore(loader().share_mem_root)

    def report_store() -> ReportStore:
        return ReportStore(RUNS_DIR if root == REPO_ROOT else root / "memory_observatory" / "runs")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/overview")
    def api_overview() -> dict[str, Any]:
        return _overview(root)

    @app.get("/api/meetings")
    def api_meetings() -> list[dict[str, Any]]:
        return memory_store().meetings()

    @app.get("/api/meetings/{meeting_id}/objects")
    def api_meeting_objects(meeting_id: str) -> list[dict[str, Any]]:
        return memory_store().objects(meeting_id=meeting_id)

    @app.get("/api/objects")
    def api_objects(meeting_id: str | None = None) -> list[dict[str, Any]]:
        return memory_store().objects(meeting_id=meeting_id)

    @app.get("/api/objects/{obj_id}")
    def api_object(obj_id: str) -> dict[str, Any]:
        detail = memory_store().object_detail(obj_id)
        if not detail:
            raise HTTPException(status_code=404, detail="object not found")
        return detail

    @app.get("/api/topics/l2")
    def api_l2_topics() -> list[dict[str, Any]]:
        return topic_store().l2_nodes()

    @app.get("/api/topics/l2/{l2_id}")
    def api_l2_topic(l2_id: str) -> dict[str, Any]:
        node = topic_store().get_l2(l2_id)
        if not node:
            raise HTTPException(status_code=404, detail="L2 not found")
        return node

    @app.get("/api/topics/l3")
    def api_l3_topics() -> dict[str, Any]:
        return topic_store().hierarchy()

    @app.get("/api/topics/l3/{l3_id}")
    def api_l3_topic(l3_id: str) -> dict[str, Any]:
        node = topic_store().get_l3(l3_id)
        if not node:
            raise HTTPException(status_code=404, detail="L3 not found")
        return node

    @app.get("/api/retrieval/trace")
    def api_retrieval_trace(
        query: str = Query(..., min_length=1),
        retrieval_mode: str = Query("hybrid", pattern="^(hybrid|lexical|semantic)$"),
        no_llm: bool = True,
        include_debug: bool = True,
        planner_model: str | None = None,
        budget_profile: str = "",
        max_context_chars: int = Query(16000, ge=0),
    ) -> dict[str, Any]:
        return RetrievalTraceService(root).run_trace(
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
