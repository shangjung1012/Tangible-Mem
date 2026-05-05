from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver

try:
    from ..agents import (
        ShortTermAgentSuite,
        build_context_planner_prompt,
        build_extraction_prompt,
        build_segment_prompt,
        flatten_agent_candidates,
    )
    from ..runtime.genai_client import GenAIConfig, create_genai_client
    from ..core.graph_state import ShortTermGraphState, memory_summary
    from ..storage.memory_tools import AgentToolContext, AgentToolPolicy
    from ..core.normalizer import normalize_memory
    from ..core.reducer import reduce_candidates
    from ..runtime.research_logger import ResearchLogger, elapsed, timed
    from ..storage.sqlite_store import save_memory_to_sqlite
    from ..storage.staging_store import (
        clear_staging_for_run,
        load_staged_candidates,
        update_staged_candidate_statuses,
    )
    from ..storage.transcript_store import load_transcript_lines
    from ..core.verifier import verify_candidates
except ImportError:  # pragma: no cover - script execution fallback
    from short_term.agents import (
        ShortTermAgentSuite,
        build_context_planner_prompt,
        build_extraction_prompt,
        build_segment_prompt,
        flatten_agent_candidates,
    )
    from short_term.runtime.genai_client import GenAIConfig, create_genai_client
    from short_term.core.graph_state import ShortTermGraphState, memory_summary
    from short_term.storage.memory_tools import AgentToolContext, AgentToolPolicy
    from short_term.core.normalizer import normalize_memory
    from short_term.core.reducer import reduce_candidates
    from short_term.runtime.research_logger import ResearchLogger, elapsed, timed
    from short_term.storage.sqlite_store import save_memory_to_sqlite
    from short_term.storage.staging_store import (
        clear_staging_for_run,
        load_staged_candidates,
        update_staged_candidate_statuses,
    )
    from short_term.storage.transcript_store import load_transcript_lines
    from short_term.core.verifier import verify_candidates


EXTRACTION_RESULT_RETRIES = 2


def run_short_term_langgraph_update(
    *,
    model_name: str,
    client_config: GenAIConfig,
    current_memory: dict[str, Any],
    memory_source: str,
    meeting_id: str,
    source_file: str,
    db_path: Path,
    transcript_db_path: Path,
    transcript_overview: dict[str, Any],
    transcript_line_count: int,
    checkpoint_db_path: Path,
    research_log_dir: Path,
    log_level: str = "debug",
    keep_full_prompts: bool = True,
    chunk_size: int = 80,
    max_lookback_lines: int = 20,
    max_lookahead_lines: int = 40,
    dry_run: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], Path]:
    logger = ResearchLogger(
        root_dir=research_log_dir,
        meeting_id=meeting_id,
        log_level=log_level,
        keep_full_prompts=keep_full_prompts,
    )
    logger.write_run_meta(
        {
            "meeting_id": meeting_id,
            "source_file": source_file,
            "model_name": model_name,
            "memory_source": memory_source,
            "db_path": str(db_path),
            "transcript_db_path": str(transcript_db_path),
            "checkpoint_db_path": str(checkpoint_db_path),
            "dry_run": dry_run,
            "chunk_size": chunk_size,
            "max_lookback_lines": max_lookback_lines,
            "max_lookahead_lines": max_lookahead_lines,
        }
    )
    clear_staging_for_run(db_path, logger.run_id)

    client = create_genai_client(client_config)
    agents = ShortTermAgentSuite(client=client, model_name=model_name)

    initial_state: ShortTermGraphState = {
        "run_id": logger.run_id,
        "meeting_id": meeting_id,
        "source_file": source_file,
        "model_name": model_name,
        "db_path": str(db_path),
        "transcript_db_path": str(transcript_db_path),
        "checkpoint_db_path": str(checkpoint_db_path),
        "research_log_dir": str(research_log_dir),
        "log_level": log_level,
        "keep_full_prompts": keep_full_prompts,
        "dry_run": dry_run,
        "chunk_size": max(1, int(chunk_size or 80)),
        "max_lookback_lines": max(0, int(max_lookback_lines or 0)),
        "max_lookahead_lines": max(0, int(max_lookahead_lines or 0)),
        "max_context_rounds": 3,
        "transcript_line_count": transcript_line_count,
        "transcript_overview": transcript_overview,
        "current_memory": current_memory,
        "memory_source": memory_source,
        "processed_until_line": 0,
        "planner_history": [],
        "context_rounds": 0,
        "unresolved_context": [],
        "meeting_window_candidates_buffer": [],
        "action_items_candidates_buffer": [],
        "method_changes_candidates_buffer": [],
        "experiment_todos_candidates_buffer": [],
        "next_meeting_focus_candidates_buffer": [],
            "raw_candidates": [],
            "tool_reads": {},
            "verified_candidates": [],
        "rejected_candidates": [],
        "final_patch": {},
        "final_memory": {},
        "report": {},
        "persisted": False,
        "read_line_numbers": [],
    }

    graph = _build_graph(
        agents=agents,
        logger=logger,
        db_path=db_path,
        transcript_db_path=transcript_db_path,
        progress_callback=progress_callback,
    )

    checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(checkpoint_db_path)) as checkpointer:
        compiled = graph.compile(checkpointer=checkpointer)
        final_state = compiled.invoke(
            initial_state,
            config={"configurable": {"thread_id": logger.run_id}},
        )

    final_memory = final_state.get("final_memory")
    if not isinstance(final_memory, dict) or not final_memory:
        raise RuntimeError("LangGraph update did not produce final_memory.")
    return final_memory, logger.run_dir


def _build_graph(
    *,
    agents: ShortTermAgentSuite,
    logger: ResearchLogger,
    db_path: Path,
    transcript_db_path: Path,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> StateGraph:
    graph = StateGraph(ShortTermGraphState)

    def load_inputs(state: ShortTermGraphState) -> dict[str, Any]:
        return _node(
            logger,
            "load_inputs",
            state,
            lambda: {
                "report": {
                    "run_id": state["run_id"],
                    "meeting_id": state["meeting_id"],
                    "memory_summary": memory_summary(state["current_memory"]),
                }
            },
            summary={
                "line_count": state.get("transcript_line_count", 0),
                "memory": memory_summary(state.get("current_memory", {})),
            },
            progress_callback=progress_callback,
        )

    def plan_next_window(state: ShortTermGraphState) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            prompt = build_context_planner_prompt(state)
            result = agents.context_planner.run(
                prompt=prompt,
                logger=logger,
                input_summary=_input_summary(state),
            )
            _raise_on_agent_errors(result, node="plan_next_window")
            parsed = result.parsed
            processed = int(state.get("processed_until_line", 0) or 0)
            total = int(state.get("transcript_line_count", 0) or 0)
            chunk_size = int(state.get("chunk_size", 80) or 80)
            plan = _sanitize_plan(
                parsed,
                processed_until=processed,
                total_lines=total,
                chunk_size=chunk_size,
                max_lookback=int(state.get("max_lookback_lines", 20) or 20),
                max_lookahead=int(state.get("max_lookahead_lines", 40) or 40),
            )
            history = list(state.get("planner_history", []))
            history.append(plan)
            return {"current_plan": plan, "planner_history": history}

        return _node(logger, "plan_next_window", state, run, progress_callback=progress_callback)

    def read_window(state: ShortTermGraphState) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            plan = state.get("current_plan", {})
            start = int(plan.get("start_line", 1) or 1)
            end = int(plan.get("end_line", start) or start)
            lookback = int(plan.get("lookback_lines", 0) or 0)
            lookahead = int(plan.get("lookahead_lines", 0) or 0)
            total = int(state.get("transcript_line_count", 0) or 0)
            context_start = max(1, start - lookback)
            context_end = min(total, end + lookahead)
            page = load_transcript_lines(
                db_path=transcript_db_path,
                meeting_id=str(state["meeting_id"]),
                start_line=context_start,
                end_line=context_end,
                limit=max(1, context_end - context_start + 1),
            )
            items = page.get("items", []) if isinstance(page, dict) else []
            line_numbers = list(state.get("read_line_numbers", []))
            for item in items:
                if isinstance(item, dict):
                    try:
                        line_numbers.append(int(item.get("line_number", 0) or 0))
                    except (TypeError, ValueError):
                        continue
            window = {
                "context_start_line": context_start,
                "context_end_line": context_end,
                "forward_start_line": start,
                "forward_end_line": end,
                "items": items,
            }
            return {
                "current_window": window,
                "read_line_numbers": sorted(set(line_numbers)),
            }

        return _node(logger, "read_window", state, run, progress_callback=progress_callback)

    def segment_window(state: ShortTermGraphState) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            prompt = build_segment_prompt(state)
            result = agents.segment.run(
                prompt=prompt,
                logger=logger,
                input_summary=_input_summary(state),
            )
            _raise_on_agent_errors(result, node="segment_window")
            units = result.parsed.get("units", [])
            if not isinstance(units, list):
                units = []
            window = state.get("current_window", {})
            allowed = _window_line_set(window)
            clean_units = [
                unit
                for unit in units
                if isinstance(unit, dict)
                and int(unit.get("line_start", 0) or 0) in allowed
                and int(unit.get("line_end", 0) or 0) in allowed
            ]
            needs_more = any(bool(unit.get("needs_more_context")) for unit in clean_units)
            unresolved_context = list(state.get("unresolved_context", []))
            window_cannot_expand = _window_cannot_expand(
                state.get("current_window", {}),
                total_lines=int(state.get("transcript_line_count", 0) or 0),
            )
            repeated_context_range = _planner_repeated_context_range(
                state.get("planner_history", []),
                total_lines=int(state.get("transcript_line_count", 0) or 0),
            )
            context_rounds = int(state.get("context_rounds", 0) or 0)
            if needs_more:
                context_rounds += 1
            else:
                context_rounds = 0
            if needs_more and window_cannot_expand:
                unresolved_context.append(
                    {
                        "line_range": _line_range(state.get("current_window", {})),
                        "reason": "segment_requested_more_context_but_window_covers_available_transcript",
                    }
                )
                needs_more = False
            elif needs_more and context_rounds > 1 and repeated_context_range:
                unresolved_context.append(
                    {
                        "line_range": _line_range(state.get("current_window", {})),
                        "reason": "segment_requested_more_context_but_planner_repeated_same_range",
                    }
                )
                needs_more = False
            elif context_rounds > int(state.get("max_context_rounds", 3) or 3):
                unresolved_context.append(
                    {
                        "line_range": _line_range(state.get("current_window", {})),
                        "reason": "segment_context_round_limit_reached",
                    }
                )
                needs_more = False
            return {
                "current_units": clean_units,
                "needs_more_context": needs_more,
                "context_rounds": context_rounds,
                "unresolved_context": unresolved_context,
            }

        return _node(logger, "segment_window", state, run, progress_callback=progress_callback)

    def start_extraction(state: ShortTermGraphState) -> dict[str, Any]:
        return _node(
            logger,
            "start_extraction",
            state,
            lambda: {},
            progress_callback=progress_callback,
        )

    def extract_meeting_summary(state: ShortTermGraphState) -> dict[str, Any]:
        return _extract_node(
            state,
            logger,
            agents.meeting,
            "meeting_window",
            "meeting_summary",
            "只產生當場 meeting summary / key_points / open_questions 候選。使用 operation=create/update/no_op；summary 不得包含 action item 細節，除非它是會議主軸。每個與會議理解有關的 unit 都要判斷是否應更新 meeting_window；相關但不更新時用 no_op 記錄原因。",
            progress_callback=progress_callback,
        )

    def extract_action_items(state: ShortTermGraphState) -> dict[str, Any]:
        return _extract_node(
            state,
            logger,
            agents.action,
            "action_items",
            "action_items",
            "只產生 action item create/update/close/no_op 候選。必須先讀 action_items；更新或關閉既有任務必須引用既有 item_id。只有明確新任務才使用 operation=create 並留空 item_id。每個含有承諾、待辦、進度、完成、取消、阻塞、負責人或下一步的 unit 都要處理；若不是 action item 或資訊不足，使用 no_op 記錄。不要把純方法討論、純 inventory 描述、或當場已完成且不需後續追蹤的執行事件寫成 action item。",
            progress_callback=progress_callback,
        )

    def extract_method_changes(state: ShortTermGraphState) -> dict[str, Any]:
        return _extract_node(
            state,
            logger,
            agents.method,
            "method_changes",
            "method_changes",
            "只處理方法、流程、實驗策略、資料處理方式的 create/update/no_op，不處理一般摘要或單純待辦。更新既有方法變更必須引用既有 change_id。每個涉及 procedure、analysis choice、data processing、experiment strategy、evaluation criteria 的 unit 都要處理；若不構成方法變更，使用 no_op 記錄。只有明確採納、切換、替換、開始使用的新 procedure/strategy 才能 create/update。單純設備 inventory、現況描述、背景脈絡、未決提議、長期願景、一般 safety/administrative TODO 不算 method change。",
            progress_callback=progress_callback,
        )

    def extract_experiment_todos(state: ShortTermGraphState) -> dict[str, Any]:
        return _extract_node(
            state,
            logger,
            agents.experiment,
            "experiment_todos",
            "experiment_todos",
            "只處理實驗執行 TODO 的 create/update/close/no_op，不處理一般行政待辦。更新或關閉既有 TODO 必須引用既有 todo_id。若 related action item 明確存在才填 related_action_item_ids。每個涉及 run experiment、prepare data、compare result、debug experiment、collect metric 的 unit 都要處理；若不構成實驗 TODO，使用 no_op 記錄。create 只保留尚未完成或仍需追蹤的實驗工作；不要把當場已完成的朗讀、已做完的執行事件、純記錄內容、或一般硬體/行政工作寫成 experiment_todo。",
            progress_callback=progress_callback,
        )

    def extract_next_focus(state: ShortTermGraphState) -> dict[str, Any]:
        return _extract_node(
            state,
            logger,
            agents.focus,
            "next_meeting_focus",
            "next_meeting_focus",
            "只產生下次會議或近期追蹤焦點的 replace/create/no_op 候選，不把 open questions 原封不動塞入。每個含有下次要看、近期要追、未決但需要 follow-up 的 unit 都要處理；若只是一般問題或已在其他 section 處理，使用 no_op 記錄。只保留真正需要後續討論的 1 到 3 個焦點；不要把所有未完議題都塞進來，也不要重複 action item 或 method change 的內容。",
            progress_callback=progress_callback,
        )

    def collect_window_candidates(state: ShortTermGraphState) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            raw = list(state.get("raw_candidates", []))
            existing_ids = {
                str(candidate.get("candidate_id", ""))
                for candidate in raw
                if isinstance(candidate, dict)
            }
            buffer_updates: dict[str, Any] = {}
            for section, agent in (
                ("meeting_window", agents.meeting),
                ("action_items", agents.action),
                ("method_changes", agents.method),
                ("experiment_todos", agents.experiment),
                ("next_meeting_focus", agents.focus),
            ):
                for candidate in state.get(_section_buffer_key(section), []):
                    if not isinstance(candidate, dict):
                        continue
                    candidate_id = str(candidate.get("candidate_id", "")).strip()
                    if candidate_id and candidate_id in existing_ids:
                        continue
                    raw.append(candidate)
                    if candidate_id:
                        existing_ids.add(candidate_id)
                staged = load_staged_candidates(
                    Path(str(state["db_path"])),
                    run_id=str(state["run_id"]),
                    agent_name=str(agent.name),
                    target_section=section,
                )
                for candidate in staged:
                    if _candidate_payload_is_sparse(candidate):
                        continue
                    candidate_id = str(candidate.get("candidate_id", ""))
                    if not candidate_id or candidate_id in existing_ids:
                        continue
                    raw.append(candidate)
                    existing_ids.add(candidate_id)
                buffer_updates[_section_buffer_key(section)] = []

            window = state.get("current_window", {})
            processed_until = max(
                int(state.get("processed_until_line", 0) or 0),
                int(window.get("forward_end_line", 0) or 0)
                if isinstance(window, dict)
                else 0,
            )
            return {
                "raw_candidates": raw,
                "processed_until_line": processed_until,
                **buffer_updates,
            }

        return _node(
            logger,
            "collect_window_candidates",
            state,
            run,
            progress_callback=progress_callback,
        )

    def verify_all_candidates(state: ShortTermGraphState) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            verified, rejected, rejection_counts = verify_candidates(
                list(state.get("raw_candidates", [])),
                current_memory=state.get("current_memory", {}),
                allowed_line_numbers={
                    int(line) for line in state.get("read_line_numbers", [])
                },
            )
            update_staged_candidate_statuses(
                db_path,
                verified_candidate_ids=_candidate_ids(verified),
                rejected_candidate_ids=_candidate_ids(rejected),
            )
            logger.candidates(
                raw=list(state.get("raw_candidates", [])),
                verified=verified,
                rejected=rejected,
            )
            report = dict(state.get("report", {}))
            report["rejection_counts"] = rejection_counts
            return {
                "verified_candidates": verified,
                "rejected_candidates": rejected,
                "report": report,
            }

        return _node(logger, "verify_candidates", state, run, progress_callback=progress_callback)

    def reduce_patch(state: ShortTermGraphState) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            patch = reduce_candidates(list(state.get("verified_candidates", [])))
            _require_current_meeting_summary(patch, meeting_id=str(state["meeting_id"]))
            return {"final_patch": patch}

        return _node(logger, "reduce_patch", state, run, progress_callback=progress_callback)

    def normalize_and_persist(state: ShortTermGraphState) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            final_memory = normalize_memory(
                updated_memory=state.get("final_patch", {}),
                previous_memory=state.get("current_memory", {}),
                meeting_id=str(state["meeting_id"]),
                source_file=str(state["source_file"]),
            )
            if not bool(state.get("dry_run", False)):
                save_memory_to_sqlite(db_path, final_memory)
            return {"final_memory": final_memory, "persisted": not state.get("dry_run", False)}

        return _node(logger, "normalize_and_persist", state, run, progress_callback=progress_callback)

    def final_report(state: ShortTermGraphState) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            report = _build_report(state, logger.run_id)
            logger.final_outputs(
                final_patch=state.get("final_patch", {}),
                final_memory=state.get("final_memory", {}),
                report=report,
            )
            return {"report": report}

        return _node(logger, "final_report", state, run, progress_callback=progress_callback)

    graph.add_node("load_inputs", load_inputs)
    graph.add_node("plan_next_window", plan_next_window)
    graph.add_node("read_window", read_window)
    graph.add_node("segment_window", segment_window)
    graph.add_node("start_extraction", start_extraction)
    graph.add_node("extract_meeting_summary", extract_meeting_summary)
    graph.add_node("extract_action_items", extract_action_items)
    graph.add_node("extract_method_changes", extract_method_changes)
    graph.add_node("extract_experiment_todos", extract_experiment_todos)
    graph.add_node("extract_next_focus", extract_next_focus)
    graph.add_node("collect_window_candidates", collect_window_candidates)
    graph.add_node("verify_candidates", verify_all_candidates)
    graph.add_node("reduce_patch", reduce_patch)
    graph.add_node("normalize_and_persist", normalize_and_persist)
    graph.add_node("final_report", final_report)

    graph.set_entry_point("load_inputs")
    graph.add_edge("load_inputs", "plan_next_window")
    graph.add_edge("plan_next_window", "read_window")
    graph.add_edge("read_window", "segment_window")
    graph.add_conditional_edges(
        "segment_window",
        _route_after_segment,
        {
            "more_context": "plan_next_window",
            "extract": "start_extraction",
        },
    )
    graph.add_edge("start_extraction", "extract_meeting_summary")
    graph.add_edge("start_extraction", "extract_action_items")
    graph.add_edge("start_extraction", "extract_method_changes")
    graph.add_edge("start_extraction", "extract_experiment_todos")
    graph.add_edge("start_extraction", "extract_next_focus")
    graph.add_edge("extract_meeting_summary", "collect_window_candidates")
    graph.add_edge("extract_action_items", "collect_window_candidates")
    graph.add_edge("extract_method_changes", "collect_window_candidates")
    graph.add_edge("extract_experiment_todos", "collect_window_candidates")
    graph.add_edge("extract_next_focus", "collect_window_candidates")
    graph.add_conditional_edges(
        "collect_window_candidates",
        _route_after_window,
        {
            "next_window": "plan_next_window",
            "verify": "verify_candidates",
        },
    )
    graph.add_edge("verify_candidates", "reduce_patch")
    graph.add_edge("reduce_patch", "normalize_and_persist")
    graph.add_edge("normalize_and_persist", "final_report")
    graph.add_edge("final_report", END)
    return graph


def _extract_node(
    state: ShortTermGraphState,
    logger: ResearchLogger,
    agent: Any,
    section: str,
    agent_kind: str,
    instructions: str,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    node_name = f"extract_{section}"

    def run() -> dict[str, Any]:
        candidates = _extract_candidates(
            state,
            logger,
            agent,
            section,
            agent_kind,
            instructions,
        )
        return {_section_buffer_key(section): candidates}

    return _node(
        logger,
        node_name,
        state,
        run,
        progress_callback=progress_callback,
    )


def _extract_candidates(
    state: ShortTermGraphState,
    logger: ResearchLogger,
    agent: Any,
    section: str,
    agent_kind: str,
    instructions: str,
) -> list[dict[str, Any]]:
    filtered_state = dict(state)
    filtered_state["current_units"] = _filter_units_for_agent(
        state.get("current_units", []),
        section=section,
    )
    if not filtered_state["current_units"]:
        return []
    prompt = build_extraction_prompt(
        agent_kind=agent_kind,
        state=filtered_state,
        instructions=instructions,
    )
    last_errors: list[str] = []
    for attempt in range(EXTRACTION_RESULT_RETRIES + 1):
        retry_prompt = prompt
        if attempt:
            retry_prompt = (
                prompt
                + "\n\nPrevious response was not usable. Return only valid JSON "
                "matching the schema. If there is no update for this section, "
                "return an empty array or no_op rows instead of prose."
            )
        result = agent.run(
            prompt=retry_prompt,
            logger=logger,
            input_summary={
                **_input_summary(filtered_state),
                "extraction_attempt": attempt + 1,
            },
            tool_context=AgentToolContext(
                db_path=Path(str(state["db_path"])),
                run_id=str(state["run_id"]),
                meeting_id=str(state["meeting_id"]),
                policy=_agent_tool_policy(str(agent.name), section),
            ),
        )
        if result.errors:
            last_errors = [str(error) for error in result.errors if str(error).strip()]
            continue
        output = _collect_agent_output(
            state=state,
            agent=agent,
            section=section,
            parsed=result.parsed,
        )
        return output

    raise RuntimeError(
        "LLM agent failed in "
        f"extract_{section} after {EXTRACTION_RESULT_RETRIES + 1} attempts: "
        f"{'; '.join(last_errors) or 'unknown error'}"
    )


def _raise_on_agent_errors(result: Any, *, node: str) -> None:
    errors = [
        str(error).strip()
        for error in getattr(result, "errors", []) or []
        if str(error).strip()
    ]
    if errors:
        agent_name = str(getattr(result, "agent_name", "agent"))
        raise RuntimeError(
            f"LLM agent failed in {node} ({agent_name}): {'; '.join(errors)}"
        )


def _require_current_meeting_summary(patch: dict[str, Any], *, meeting_id: str) -> None:
    rows = patch.get("meeting_window") if isinstance(patch, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(
            f"Missing meeting_window summary for meeting_id={meeting_id}; refusing to persist."
        )
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("meeting_id", "")).strip() != meeting_id:
            continue
        if str(row.get("summary", "")).strip():
            return
    raise RuntimeError(
        f"Missing meeting_window summary for meeting_id={meeting_id}; refusing to persist."
    )


def _candidate_ids(candidates: list[dict[str, Any]]) -> set[str]:
    return {
        str(candidate.get("candidate_id", "")).strip()
        for candidate in candidates
        if isinstance(candidate, dict) and str(candidate.get("candidate_id", "")).strip()
    }


def _collect_agent_output(
    *,
    state: ShortTermGraphState,
    agent: Any,
    section: str,
    parsed: dict[str, Any],
) -> list[dict[str, Any]]:
    staged = load_staged_candidates(
        Path(str(state["db_path"])),
        run_id=str(state["run_id"]),
        agent_name=str(agent.name),
        target_section=section,
    )
    parsed_candidates = flatten_agent_candidates(agent.name, section, parsed)
    existing_ids = {
        str(candidate.get("candidate_id", ""))
        for candidate in state.get("raw_candidates", [])
        if isinstance(candidate, dict)
    }

    output: list[dict[str, Any]] = [
        candidate
        for candidate in staged
        if str(candidate.get("candidate_id", "")) not in existing_ids
        and not _candidate_payload_is_sparse(candidate)
    ]

    # Gemini tool-calling sometimes writes staging rows with an empty or nearly
    # empty candidate_payload, while the final JSON response still contains the
    # full structured candidate. Keep the parsed JSON candidates as a fallback
    # so verifier/reducer can still operate on complete payloads.
    if not output or any(_candidate_payload_is_sparse(row) for row in staged):
        output.extend(parsed_candidates)
        return output

    staged_signatures = {_candidate_signature(row) for row in output}
    for candidate in parsed_candidates:
        signature = _candidate_signature(candidate)
        if signature in staged_signatures:
            continue
        output.append(candidate)
    return output


def _candidate_payload_is_sparse(candidate: dict[str, Any]) -> bool:
    payload = candidate.get("payload")
    if not isinstance(payload, dict):
        return True
    operation = str(candidate.get("operation") or payload.get("operation") or "").strip()
    if operation == "no_op":
        return False
    content_keys = {
        str(key).strip()
        for key, value in payload.items()
        if str(key).strip()
        and key not in {"operation", "confidence", "evidence"}
        and value not in (None, "", [], {})
    }
    return not content_keys


def _candidate_signature(candidate: dict[str, Any]) -> tuple[str, str, str, str]:
    payload = candidate.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}
    operation = str(
        candidate.get("operation")
        or payload.get("operation")
        or ""
    ).strip()
    target_id = str(candidate.get("target_id", "")).strip()
    payload_json = str(sorted(payload.items()))
    return (
        str(candidate.get("section", "")).strip(),
        operation,
        target_id,
        payload_json,
    )


def _filter_units_for_agent(units: Any, *, section: str) -> list[dict[str, Any]]:
    if not isinstance(units, list):
        return []
    normalized_units = [unit for unit in units if isinstance(unit, dict)]
    if section == "meeting_window":
        return normalized_units

    allowed_hints = {
        "action_items": {
            "action_item",
            "action_items",
            "task",
            "todo",
            "next_step",
            "blocker",
            "decision",
        },
        "method_changes": {
            "method_change",
            "method_changes",
            "process",
            "procedure",
            "workflow",
            "decision",
            "analysis_choice",
        },
        "experiment_todos": {
            "experiment_todo",
            "experiment_todos",
            "experiment",
            "research",
            "data_collection",
            "metric",
            "debug",
        },
        "next_meeting_focus": {
            "next_focus",
            "next_meeting_focus",
            "follow_up",
            "open_question",
            "planning",
            "research_direction",
            "problem",
        },
    }.get(section, set())
    keywords = {
        "action_items": (
            "need to",
            "should",
            "will",
            "next",
            "follow up",
            "todo",
            "task",
            "owner",
            "blocked",
        ),
        "method_changes": (
            "procedure",
            "workflow",
            "process",
            "strategy",
            "analysis",
            "segment",
            "recognition",
            "resampling",
            "change",
            "start doing",
            "instead of",
        ),
        "experiment_todos": (
            "experiment",
            "collect data",
            "prepare data",
            "run",
            "compare",
            "metric",
            "debug",
            "recognition",
            "segmentation",
        ),
        "next_meeting_focus": (
            "next time",
            "follow up",
            "bring that up",
            "need to discuss",
            "unresolved",
            "clarify",
            "track",
            "figure out",
        ),
    }.get(section, ())

    matched: list[dict[str, Any]] = []
    for unit in normalized_units:
        hints = {
            str(value).strip().lower().replace("-", "_")
            for value in unit.get("kind_hint", [])
            if str(value).strip()
        }
        text = " ".join(
            str(unit.get(key, "")).strip().lower()
            for key in ("topic", "reason")
        )
        if hints & allowed_hints:
            matched.append(unit)
            continue
        if any(keyword in text for keyword in keywords):
            matched.append(unit)
    return matched


def _section_buffer_key(section: str) -> str:
    return f"{section}_candidates_buffer"


def _agent_tool_policy(agent_name: str, section: str) -> AgentToolPolicy:
    policies = {
        "meeting_summary_agent": AgentToolPolicy(
            agent_name=agent_name,
            read_sections={"overview", "meeting_window"},
            required_read_sections=set(),
            write_sections={"meeting_window"},
        ),
        "action_item_agent": AgentToolPolicy(
            agent_name=agent_name,
            read_sections={"overview", "action_items"},
            required_read_sections=set(),
            write_sections={"action_items"},
        ),
        "method_change_agent": AgentToolPolicy(
            agent_name=agent_name,
            read_sections={"overview", "method_changes"},
            required_read_sections=set(),
            write_sections={"method_changes"},
        ),
        "experiment_todo_agent": AgentToolPolicy(
            agent_name=agent_name,
            read_sections={"overview", "experiment_todos", "action_items"},
            required_read_sections=set(),
            write_sections={"experiment_todos"},
        ),
        "next_focus_agent": AgentToolPolicy(
            agent_name=agent_name,
            read_sections={
                "overview",
                "action_items",
                "method_changes",
                "experiment_todos",
                "next_meeting_focus",
            },
            required_read_sections=set(),
            write_sections={"next_meeting_focus"},
        ),
    }
    return policies.get(
        agent_name,
        AgentToolPolicy(agent_name=agent_name, read_sections={"overview"}, write_sections={section}),
    )


def _route_after_segment(state: ShortTermGraphState) -> str:
    return "more_context" if state.get("needs_more_context") else "extract"


def _route_after_window(state: ShortTermGraphState) -> str:
    processed = int(state.get("processed_until_line", 0) or 0)
    total = int(state.get("transcript_line_count", 0) or 0)
    return "next_window" if processed < total else "verify"


def _sanitize_plan(
    raw: dict[str, Any],
    *,
    processed_until: int,
    total_lines: int,
    chunk_size: int,
    max_lookback: int,
    max_lookahead: int,
) -> dict[str, Any]:
    default_start = min(total_lines, processed_until + 1) if total_lines else 1
    start = _safe_int(raw.get("start_line"), default_start)
    if start <= processed_until:
        start = default_start
    start = max(1, min(total_lines or 1, start))
    end = _safe_int(raw.get("end_line"), start + chunk_size - 1)
    end = max(start, min(total_lines or start, end))
    if end - start + 1 > chunk_size:
        end = min(total_lines or end, start + chunk_size - 1)
    lookback = max(0, min(max_lookback, _safe_int(raw.get("lookback_lines"), 0)))
    lookahead = max(0, min(max_lookahead, _safe_int(raw.get("lookahead_lines"), 0)))
    risk = str(raw.get("risk", "medium")).strip().lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"
    return {
        "start_line": start,
        "end_line": end,
        "lookback_lines": lookback,
        "lookahead_lines": lookahead,
        "reason": str(raw.get("reason", "default sanitized plan")).strip(),
        "risk": risk,
    }


def _node(
    logger: ResearchLogger,
    name: str,
    state: ShortTermGraphState,
    fn: Any,
    *,
    summary: dict[str, Any] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    started = timed()
    logger.graph_event(
        node=name,
        event="start",
        summary=summary or {},
        line_range=_line_range(state.get("current_window", {})),
    )
    _emit_progress(
        progress_callback,
        state=state,
        node=name,
        event="start",
        summary=summary or {},
    )
    try:
        updates = fn()
        merged = dict(state)
        merged.update(updates)
        node_summary = _node_summary(name, merged)
        duration = elapsed(started)
        logger.state_snapshot(name, merged)
        logger.graph_event(
            node=name,
            event="end",
            duration_seconds=duration,
            summary=node_summary,
            line_range=_line_range(merged.get("current_window", {})),
        )
        _emit_progress(
            progress_callback,
            state=merged,
            node=name,
            event="end",
            summary=node_summary,
            duration_seconds=duration,
        )
        return updates
    except Exception as exc:
        duration = elapsed(started)
        logger.graph_event(
            node=name,
            event="end",
            status="error",
            duration_seconds=duration,
            summary={"error": str(exc)},
            line_range=_line_range(state.get("current_window", {})),
        )
        _emit_progress(
            progress_callback,
            state=state,
            node=name,
            event="error",
            summary={"error": str(exc)},
            duration_seconds=duration,
        )
        raise


def _emit_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    *,
    state: dict[str, Any],
    node: str,
    event: str,
    summary: dict[str, Any],
    duration_seconds: float | None = None,
) -> None:
    if callback is None:
        return
    try:
        callback(
            {
                "run_id": state.get("run_id", ""),
                "meeting_id": state.get("meeting_id", ""),
                "node": node,
                "event": event,
                "duration_seconds": duration_seconds,
                "processed_until_line": state.get("processed_until_line", 0),
                "transcript_line_count": state.get("transcript_line_count", 0),
                "line_range": _line_range(state.get("current_window", {})),
                "raw_candidates": len(state.get("raw_candidates", [])),
                "verified_candidates": len(state.get("verified_candidates", [])),
                "rejected_candidates": len(state.get("rejected_candidates", [])),
                "summary": summary,
            }
        )
    except Exception:
        return


def _node_summary(name: str, state: dict[str, Any]) -> dict[str, Any]:
    if name == "segment_window":
        return {
            "units": len(state.get("current_units", [])),
            "needs_more_context": bool(state.get("needs_more_context")),
            "unresolved_context_count": len(state.get("unresolved_context", [])),
        }
    if name.startswith("extract_"):
        return {"raw_candidates": len(state.get("raw_candidates", []))}
    if name == "verify_candidates":
        return {
            "verified": len(state.get("verified_candidates", [])),
            "rejected": len(state.get("rejected_candidates", [])),
        }
    if name == "reduce_patch":
        return {
            key: len(value) if isinstance(value, list) else 1
            for key, value in state.get("final_patch", {}).items()
        }
    if name == "normalize_and_persist":
        return {
            "persisted": bool(state.get("persisted")),
            "memory": memory_summary(state.get("final_memory", {})),
        }
    return {}


def _input_summary(state: dict[str, Any]) -> dict[str, Any]:
    window = state.get("current_window", {})
    return {
        "meeting_id": state.get("meeting_id"),
        "processed_until_line": state.get("processed_until_line"),
        "transcript_line_count": state.get("transcript_line_count"),
        "line_range": _line_range(window),
        "memory": memory_summary(state.get("current_memory", {})),
        "raw_candidates": len(state.get("raw_candidates", [])),
    }


def _line_range(window: Any) -> str:
    if not isinstance(window, dict):
        return ""
    start = window.get("context_start_line")
    end = window.get("context_end_line")
    if not start or not end:
        return ""
    return f"L{start}-L{end}"


def _window_line_set(window: Any) -> set[int]:
    if not isinstance(window, dict):
        return set()
    output: set[int] = set()
    for item in window.get("items", []):
        if not isinstance(item, dict):
            continue
        try:
            output.add(int(item.get("line_number", 0) or 0))
        except (TypeError, ValueError):
            continue
    return output


def _window_cannot_expand(window: Any, *, total_lines: int) -> bool:
    if not isinstance(window, dict) or total_lines <= 0:
        return False
    try:
        context_start = int(window.get("context_start_line", 0) or 0)
        context_end = int(window.get("context_end_line", 0) or 0)
    except (TypeError, ValueError):
        return False
    return context_start <= 1 and context_end >= total_lines


def _planner_repeated_context_range(planner_history: Any, *, total_lines: int) -> bool:
    if not isinstance(planner_history, list) or len(planner_history) < 2:
        return False
    last = planner_history[-1]
    previous = planner_history[-2]
    if not isinstance(last, dict) or not isinstance(previous, dict):
        return False
    return _plan_context_range(last, total_lines=total_lines) == _plan_context_range(
        previous,
        total_lines=total_lines,
    )


def _plan_context_range(plan: dict[str, Any], *, total_lines: int) -> tuple[int, int]:
    start = _safe_int(plan.get("start_line"), 1)
    end = _safe_int(plan.get("end_line"), start)
    lookback = _safe_int(plan.get("lookback_lines"), 0)
    lookahead = _safe_int(plan.get("lookahead_lines"), 0)
    context_start = max(1, start - max(0, lookback))
    context_end = min(max(total_lines, 1), end + max(0, lookahead))
    return context_start, context_end


def _build_report(state: dict[str, Any], run_id: str) -> dict[str, Any]:
    rejected = state.get("rejected_candidates", [])
    rejection_counts = Counter(
        reason
        for row in rejected
        if isinstance(row, dict)
        for reason in row.get("rejection_reasons", [])
    )
    final_memory = state.get("final_memory", {})
    final_patch = state.get("final_patch", {})
    warnings: list[str] = []
    warning_counts = Counter(
        warning
        for row in state.get("verified_candidates", []) + state.get("rejected_candidates", [])
        if isinstance(row, dict)
        for warning in row.get("warnings", [])
    )
    if warning_counts.get("missing_evidence", 0):
        warnings.append("Some candidates had no evidence and were kept for debug review.")
    if rejection_counts.get("low_confidence", 0):
        warnings.append("Some candidates were rejected because confidence was low.")
    unresolved_context = state.get("unresolved_context", [])
    if unresolved_context:
        warnings.append("Some transcript windows requested more context but could not be expanded further.")
    if not final_patch:
        warnings.append("No verified candidate produced a final patch.")
    return {
        "run_id": run_id,
        "meeting_id": state.get("meeting_id", ""),
        "processed_until_line": state.get("processed_until_line", 0),
        "transcript_line_count": state.get("transcript_line_count", 0),
        "candidate_counts": {
            "raw": len(state.get("raw_candidates", [])),
            "verified": len(state.get("verified_candidates", [])),
            "rejected": len(state.get("rejected_candidates", [])),
        },
        "rejection_counts": dict(rejection_counts),
        "warning_counts": dict(warning_counts),
        "staged_operations": _candidate_operation_counts(state.get("raw_candidates", [])),
        "final_writes": _final_write_summary(state.get("verified_candidates", [])),
        "unresolved_context": unresolved_context if isinstance(unresolved_context, list) else [],
        "final": {
            "memory_version": final_memory.get("memory_version", ""),
            "meeting_window": len(final_memory.get("meeting_window", []))
            if isinstance(final_memory, dict)
            else 0,
            "action_items": len(final_memory.get("action_items", []))
            if isinstance(final_memory, dict)
            else 0,
            "patch_sections": sorted(final_patch.keys())
            if isinstance(final_patch, dict)
            else [],
        },
        "warnings": warnings,
    }


def _candidate_operation_counts(candidates: Any) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if not isinstance(candidates, list):
        return {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        payload = candidate.get("payload", {})
        operation = str(
            candidate.get("operation")
            or (payload.get("operation") if isinstance(payload, dict) else "")
            or "unknown"
        )
        section = str(candidate.get("section", "unknown"))
        counts[f"{section}:{operation}"] += 1
    return dict(counts)


def _final_write_summary(candidates: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    if not isinstance(candidates, list):
        return output
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        payload = candidate.get("payload", {})
        operation = candidate.get("operation") or (
            payload.get("operation") if isinstance(payload, dict) else ""
        )
        if operation == "no_op":
            continue
        output.append(
            {
                "candidate_id": candidate.get("candidate_id", ""),
                "agent": candidate.get("agent", ""),
                "section": candidate.get("section", ""),
                "operation": operation,
                "target_id": candidate.get("target_id", ""),
                "warnings": candidate.get("warnings", []),
            }
        )
    return output


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
