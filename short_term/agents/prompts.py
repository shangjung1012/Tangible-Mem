from __future__ import annotations

import json
from typing import Any

try:
    from ..core.graph_state import action_item_index, memory_summary, transcript_items_text
except ImportError:  # pragma: no cover - script execution fallback
    from short_term.core.graph_state import action_item_index, memory_summary, transcript_items_text

PROMPT_VERSION = "short-term-langgraph-v1"
DEFAULT_TEMPERATURE = 0.1

COMMON_RULES = """
你是 Virtual Mentor short-term memory pipeline 的受限子代理。
你不能直接更新 official memory，不能輸出完整 memory。
若可使用工具，需要讀 current memory 時只能呼叫 read_short_term_memory。
若要提出記憶候選，必須呼叫 write_memory_candidate 寫入 staging DB；最後 JSON 只作為 summary。
evidence_lines/evidence_quote 用於 research log/debug，盡量填寫，但不是所有候選的硬性判斷條件。
你必須逐一處理輸入中的所有 idea units；不能因為資訊不完整就忽略，應使用 no_op 或 uncertainty 說明。
不得臆測 owner、status、priority、決策結果；不確定時填 unknown 或輸出 uncertainty。
不得改寫未被要求負責的 section。
輸出必須是 JSON only。
""".strip()


def build_context_planner_prompt(state: dict[str, Any]) -> str:
    processed = int(state.get("processed_until_line", 0) or 0)
    return f"""
{COMMON_RULES}

你只負責規劃下一次讀取範圍，不抽取記憶。
若上一段開頭像延續前文，要求 lookback。
若上一段結尾句意未完、討論正在轉折、有人提出問題但尚未回答，要求 lookahead。
不要為了抽取方便要求過大範圍。

限制：
- forward window 建議 {state.get('chunk_size', 80)} 行。
- lookback_lines 不得超過 {state.get('max_lookback_lines', 20)}。
- lookahead_lines 不得超過 {state.get('max_lookahead_lines', 40)}。
- start_line 必須從 processed_until_line + 1 開始，除非正在補上下文。

Meeting:
- meeting_id: {state.get('meeting_id')}
- total_lines: {state.get('transcript_line_count')}
- processed_until_line: {processed}

Transcript overview:
{json.dumps(state.get('transcript_overview', {}), ensure_ascii=False, indent=2)}

Current memory summary:
{json.dumps(memory_summary(state.get('current_memory', {})), ensure_ascii=False, indent=2)}

Planner history:
{json.dumps(state.get('planner_history', [])[-5:], ensure_ascii=False, indent=2)}
""".strip()


def build_segment_prompt(state: dict[str, Any]) -> str:
    window = state.get("current_window", {})
    items = window.get("items", []) if isinstance(window, dict) else []
    return f"""
{COMMON_RULES}

你只負責把 transcript window 切成完整 idea units，不抽取記憶。
如果一個 topic 尚未講完，needs_more_context 必須為 true。
line_start/line_end 必須落在提供的 transcript lines 內。
不要因為 topic 看似瑣碎就省略；所有可能影響 meeting summary、action item、method change、experiment todo、next focus 的對話都要切成 unit。
kind_hint 可包含多個可能 section；不確定時保守加入可能的 hint，讓後續 agent 判斷。

Window:
{json.dumps(_window_summary(window), ensure_ascii=False, indent=2)}

Transcript lines:
{transcript_items_text(items)}
""".strip()


def build_extraction_prompt(
    *,
    agent_kind: str,
    state: dict[str, Any],
    instructions: str,
) -> str:
    window = state.get("current_window", {})
    items = window.get("items", []) if isinstance(window, dict) else []
    return f"""
{COMMON_RULES}

Agent responsibility:
{instructions}

Tool rules:
- 需要 current memory 時呼叫 read_short_term_memory。
- 產生候選時呼叫 write_memory_candidate 寫入 staging；不要只把候選放在最後 JSON。
- write_memory_candidate 必須包含 operation、target_section、candidate_payload、confidence、note。
- candidate_payload 不能是空物件，也不能只包含 operation/confidence/evidence；必須把該 section 的實質欄位放進 candidate_payload。
- action_items create 的 candidate_payload 必須包含 title、detail、proposer、owner、status、priority、dependencies；新 action item 的 item_id 必須留空，系統會分配 A###。update/close 必須使用 read_short_term_memory 讀到的既有 A### item_id。
- action_items 的 status 只能是 open、in_progress、completed、cancelled；priority 只能是 high、medium、low。
- method_changes create 的 candidate_payload 必須包含 topic、before、after、reason、status；experiment_todos create 必須包含 description、status、owner、related_action_item_ids。
- update/close/replace 必須填 target_id；create 可留空 target_id。
- evidence_lines/evidence_quote 請盡量填，供 research log/debug 使用。
- 你必須逐一檢查 Accepted idea units。若某個 unit 與你的責任無關，可以不寫候選；若相關但不應更新，請用 operation=no_op 寫入 staging 並在 note 說明原因。
- 若需要比對既有項目，必須先 read_short_term_memory 讀你的 section，再決定 create/update/close/replace/no_op。
- 不要只因欄位不完整就跳過：可用 unknown、空陣列或 no_op 表達不確定，但要讓 log 看得出你處理過。
- 最後 JSON summary 必須反映已寫入 staging 的候選；不要在 JSON 中新增未透過 tool 寫入的候選。

Meeting metadata:
- meeting_id: {state.get('meeting_id')}
- source_file: {state.get('source_file')}

Current memory summary:
{json.dumps(memory_summary(state.get('current_memory', {})), ensure_ascii=False, indent=2)}

Current action item index:
{json.dumps(action_item_index(state.get('current_memory', {})), ensure_ascii=False, indent=2)}

Accepted idea units:
{json.dumps(state.get('current_units', []), ensure_ascii=False, indent=2)}

Transcript lines:
{transcript_items_text(items)}

輸出只能包含 {agent_kind} schema 負責的欄位。沒有明確 create/update/close/replace 時，若有相關但不更新的 unit，仍應先用 write_memory_candidate 寫 no_op staging candidate；最後 JSON 可回傳空陣列或 summary。
""".strip()


def _window_summary(window: Any) -> dict[str, Any]:
    if not isinstance(window, dict):
        return {}
    return {
        "context_start_line": window.get("context_start_line"),
        "context_end_line": window.get("context_end_line"),
        "forward_start_line": window.get("forward_start_line"),
        "forward_end_line": window.get("forward_end_line"),
        "returned_count": len(window.get("items", [])),
    }
