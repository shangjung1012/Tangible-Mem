from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from google import genai
from google.genai import errors, types

from normalizer import normalize_memory
from schema import RESPONSE_JSON_SCHEMA, SCHEMA_DESCRIPTION

MAX_GENERATION_ATTEMPTS = 3
MAX_TOOL_ROUNDS: int | None = None
MAX_API_RETRIES = 15
API_RETRY_BASE_DELAY_SECONDS = 2.0
API_RETRY_MAX_DELAY_SECONDS = 20.0
DEFAULT_TOOL_PAGE_SIZE = 10
MAX_OVERVIEW_INDEX_ITEMS = 80
MAX_PATCH_SECTIONS_PER_WRITE = 2
HEAVY_READ_REQUIRED_SECTIONS = {
    "action_items",
    "method_changes",
    "experiment_todos",
}
WRITABLE_MEMORY_SECTIONS = [
    "meeting_window",
    "action_items",
    "method_changes",
    "experiment_todos",
    "next_meeting_focus",
]


def build_tool_call_prompt(
    meeting_id: str,
    source_file: str,
    transcript_line_count: int,
) -> str:
    return f"""
你是一個「短期記憶 SQLite 更新器」。
你必須使用工具完成更新，而不是直接在文字回覆最終 JSON。
逐字稿已先匯入 SQLite；你不能一次拿到完整逐字稿，必須用工具分段讀取。

任務流程（必須遵守）：
1) 先呼叫 `read_short_term_memory(section="overview")` 取得目前記憶總覽。
2) 再呼叫 `read_transcript_overview()` 取得逐字稿行數與頭尾預覽。
3) 使用 `read_transcript_lines(start_line, end_line, limit)` 分段讀逐字稿。你可以自己決定每次讀幾行、從哪行讀到哪行；建議一次 40-80 行，最多依工具限制。
4) 每讀完一段，就判斷該段是否形成完整主題/idea unit；如果內容延續到下一段，可以繼續讀下一段再寫。
5) 當你已經確認一小批更新時，就立刻呼叫 `write_short_term_memory` 寫入該批 patch，然後繼續讀下一段逐字稿。
6) 根據 transcript 內容判斷需要哪些 memory section，再用 `read_short_term_memory` 分批讀取相關 section。
7) 只讀你真的需要的 memory 部分；不要一開始就把完整 memory 全部讀回來。
8) 你可以多次呼叫 `write_short_term_memory`，每次只寫「新增或變動的部分」，不要把整份 memory 原封不動回寫。
9) 完成必要更新後，只做簡短確認，不要輸出最終 JSON。

更新規則：
- 盡量保留既有 item_id / change_id / todo_id，不要無故改號。
- 新增項目才新增新 id。
- 若逐字稿顯示完成/取消/方法修正，更新 status 或 method_changes。
- evidence 優先寫逐字稿中的短證據句，並盡量附上行號，例如「L42-L47: ...」。
- 若無法確定 owner / proposer，填 unknown。
- 文字欄位請優先繁體中文。
- 系統會在本地維護 meeting_history_ids，並裁切 meeting_window 成最近三次；你只要提供合理更新即可。
- `write_short_term_memory` 可以接受 partial patch；省略的欄位代表保持原狀。
- 若 action items / method changes / experiment todos 很多，請使用 `offset` + `limit` 分頁讀取。
- overview 會提供 compact `action_item_index`；新增 action item 前，必須先用這個 index 檢查是否其實是在延續現有 item。
- 只有在非常確定 memory 很小、或真的無法分批完成時，才可使用 `section="full"`。
- 不要嘗試一次讀完整 transcript；如果 transcript 很短，也請至少透過 `read_transcript_lines` 讀取。
- 在寫入 `action_items` / `method_changes` / `experiment_todos` 之前，必須先讀過對應 section，否則寫入會被拒絕。
- 如果要新增沒有 `item_id` 的 action item，且現有 action items 超過一頁，請先讀完整 action_items 分頁，避免把現有任務誤判成新任務。
- 每次寫入最多只更新少數 top-level sections；如果有很多變更，請拆成多次 write。
- 如果工具回傳 no-op 或 prerequisite read error，代表你需要先多讀一點，再提交更小的 patch。
- 不要重複提交沒有實際變化的 patch。

Transcript 工具回傳格式：
- `read_transcript_overview()` 會回傳 `line_count`、頭尾少量預覽、建議起始行。
- `read_transcript_lines(...)` 的每個 item 都包含：
  - `line_number`：逐字稿行號，可作為 evidence 的 Lxx
  - `speaker`：說話者，例如 `me011`、`fe016`、`SPEAKER_00`
  - `text`：該 speaker 說的內容，不含 `[speaker]:`
  - `raw_line`：原始整行，例如 `[me011]: OK, so we're live.`
- 判斷內容時請優先使用 `speaker` 與 `text` 欄位，不要再自行解析 `raw_line`。

建議策略：
- 第一步永遠先讀 memory `overview`，第二步讀 transcript overview。
- 從第 1 行開始分段讀 transcript，維持一個「已處理到第幾行」的內部進度。
- 如果 `read_transcript_lines` 回傳 `has_more=true`，下一次優先使用 `next_start_line` 繼續讀。
- 如果某段只是在延續上一段主題，先不要急著寫；等 idea unit 完整後再寫。
- 若讀到新的短期事項、會議安排、待辦、狀態變更或下次討論重點，先查相關 memory section，再寫 patch。
- 先用 overview 的 `action_item_index` 找候選既有 action item；若語意相關，更新既有 `item_id`。
- 如果要找既有 action item / method change / experiment todo 的完整內容，再分頁讀該 section，而不是直接讀 full。
- 若會議中同時有多個更新，請按主題或項目分批寫入，例如先寫 meeting summary，再寫 action items，再寫 method changes。
- 每次寫入只帶必要欄位，例如：
  - 只更新 meeting summary：傳 `meeting_window`
  - 只更新部分 action items：傳 `action_items`
  - 只更新 next_meeting_focus：傳 `next_meeting_focus`
- `write_short_term_memory` 的 `note` 請簡短標明依據的 transcript 行號範圍，方便 debug。

Schema 說明（欄位參考）：
{json.dumps(SCHEMA_DESCRIPTION, ensure_ascii=False, indent=2)}

Current meeting metadata:
- meeting_id: {meeting_id}
- source_file: {source_file}
- transcript_line_count: {transcript_line_count}
""".strip()


def build_structured_prompt(
    transcript: str,
    current_memory: dict[str, Any],
    meeting_id: str,
    source_file: str,
) -> str:
    return f"""
你是一個「短期記憶更新器」。
任務：根據單次會議逐字稿，更新 short-term memory。

你必須遵守：
1) 回傳 JSON only，不要有任何額外文字。
2) JSON 結構固定，欄位名稱與型態必須符合 schema。
3) 必須保留舊記憶資訊，僅新增/更新，不能任意刪除未完成項目。
4) meeting_window 不需要負責刪除舊會議；請至少正確提供目前會議的摘要，最近三次的裁切會由系統在本地完成。
5) action_items 要盡量維持 item_id 一致；新項目才新增新 id。系統會在本地只保留最近三次會議範圍內建立或更新過的 action items。
6) 若逐字稿有完成/取消/方法修正跡象，要更新 status 或 method_changes。
7) 能從逐字稿抓到證據時，寫在 evidence 欄位（短句即可）。
8) memory_version 應該是 current_memory.memory_version + 1。
9) 文字欄位請優先使用繁體中文。
10) 若無法確定 owner / proposer，請填 unknown，不要臆測。
11) `meeting_history_ids` 是系統在本地維護的順序欄位；如果你輸出它，請原樣保留 current_memory 的值，不要自行推測或重建。

Schema:
{json.dumps(SCHEMA_DESCRIPTION, ensure_ascii=False, indent=2)}

Current memory JSON:
{json.dumps(current_memory, ensure_ascii=False, indent=2)}

Current meeting metadata:
- meeting_id: {meeting_id}
- source_file: {source_file}

Transcript:
{transcript}
""".strip()


def extract_json(raw_text: str, parsed: Any | None = None) -> dict[str, Any]:
    if isinstance(parsed, dict):
        return parsed

    if hasattr(parsed, "model_dump"):
        dumped = parsed.model_dump()
        if isinstance(dumped, dict):
            return dumped

    text = (raw_text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        raise RuntimeError("Gemini response does not contain valid JSON object.")

    candidate = text[start : end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse Gemini JSON output.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Gemini JSON output must be an object.")
    return data


def save_failed_response(
    meeting_id: str,
    attempt: int,
    raw_text: str,
    suffix: str = "",
) -> Path:
    debug_dir = Path(__file__).resolve().parent / "debug_raw"
    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix_str = f"_{suffix}" if suffix else ""
    path = debug_dir / f"{timestamp}_{meeting_id}_attempt{attempt}{suffix_str}.txt"
    path.write_text(raw_text or "", encoding="utf-8")
    return path


def _is_retryable_genai_error(exc: Exception) -> bool:
    if isinstance(exc, errors.ServerError):
        return True

    message = str(exc).upper()
    return "503" in message or "UNAVAILABLE" in message


def _call_with_retry(
    func: Callable[[], Any],
    *,
    log: Callable[[str], None],
    operation_name: str,
    max_retries: int = MAX_API_RETRIES,
) -> Any:
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            if not _is_retryable_genai_error(exc) or attempt >= max_retries:
                raise

            delay_seconds = min(
                API_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
                API_RETRY_MAX_DELAY_SECONDS,
            )
            log(
                f"{operation_name} failed with retryable error "
                f"(attempt {attempt}/{max_retries}): {exc}. "
                f"sleep {delay_seconds:.1f}s before retry"
            )
            time.sleep(delay_seconds)


def _generate_structured_update(
    client: genai.Client,
    model_name: str,
    transcript: str,
    current_memory: dict[str, Any],
    meeting_id: str,
    source_file: str,
    log: Callable[[str], None],
) -> dict[str, Any]:
    prompt = build_structured_prompt(
        transcript=transcript,
        current_memory=current_memory,
        meeting_id=meeting_id,
        source_file=source_file,
    )
    response = _call_with_retry(
        lambda: client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={
                "temperature": 0.0,
                "response_mime_type": "application/json",
                "response_json_schema": RESPONSE_JSON_SCHEMA,
            },
        ),
        log=log,
        operation_name="structured generate_content",
    )
    return extract_json(response.text or "", parsed=getattr(response, "parsed", None))


def _short_text(value: Any, max_chars: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _compact_action_item_index(memory: dict[str, Any]) -> list[dict[str, str]]:
    index: list[dict[str, str]] = []
    for row in memory.get("action_items", []):
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("item_id", "")).strip()
        if not item_id:
            continue
        history = row.get("history", [])
        history_count = len(history) if isinstance(history, list) else 0
        index.append(
            {
                "item_id": item_id,
                "title": _short_text(row.get("title"), 90),
                "detail_hint": _short_text(row.get("detail"), 140),
                "status": str(row.get("status", "")).strip(),
                "priority": str(row.get("priority", "")).strip(),
                "owner": _short_text(row.get("owner"), 60),
                "created_meeting_id": str(row.get("created_meeting_id", "")).strip(),
                "last_updated_meeting_id": str(
                    row.get("last_updated_meeting_id", "")
                ).strip(),
                "history_count": str(history_count),
            }
        )
        if len(index) >= MAX_OVERVIEW_INDEX_ITEMS:
            break
    return index


def _slice_memory_section(
    memory: dict[str, Any],
    section: str,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    normalized_section = str(section or "overview").strip().lower()
    safe_offset = max(int(offset or 0), 0)
    safe_limit = max(int(limit or DEFAULT_TOOL_PAGE_SIZE), 1)

    if normalized_section == "full":
        return {
            "section": "full",
            "memory": memory,
            "summary": {
                "memory_version": int(memory.get("memory_version", 0) or 0),
                "meeting_history_count": len(memory.get("meeting_history_ids", [])),
                "meeting_window_count": len(memory.get("meeting_window", [])),
                "action_items_count": len(memory.get("action_items", [])),
                "method_changes_count": len(memory.get("method_changes", [])),
                "experiment_todos_count": len(memory.get("experiment_todos", [])),
                "next_meeting_focus_count": len(memory.get("next_meeting_focus", [])),
            },
        }

    if normalized_section == "overview":
        action_items = list(memory.get("action_items", []))
        action_item_index = _compact_action_item_index(memory)
        return {
            "section": "overview",
            "summary": {
                "memory_version": int(memory.get("memory_version", 0) or 0),
                "last_updated_meeting_id": str(memory.get("last_updated_meeting_id", "")),
                "meeting_history_ids": list(memory.get("meeting_history_ids", [])),
                "meeting_window_ids": [
                    row.get("meeting_id", "")
                    for row in memory.get("meeting_window", [])
                    if isinstance(row, dict)
                ],
                "meeting_history_count": len(memory.get("meeting_history_ids", [])),
                "meeting_window_count": len(memory.get("meeting_window", [])),
                "action_items_count": len(action_items),
                "method_changes_count": len(memory.get("method_changes", [])),
                "experiment_todos_count": len(memory.get("experiment_todos", [])),
                "next_meeting_focus_count": len(memory.get("next_meeting_focus", [])),
            },
            "action_item_index": action_item_index,
            "action_item_index_truncated": len(action_item_index) < len(action_items),
            "recommended_sections": [
                "meeting_window",
                "action_items",
                "method_changes",
                "experiment_todos",
                "next_meeting_focus",
            ],
        }

    section_map: dict[str, list[Any]] = {
        "meeting_window": list(memory.get("meeting_window", [])),
        "action_items": list(memory.get("action_items", [])),
        "method_changes": list(memory.get("method_changes", [])),
        "experiment_todos": list(memory.get("experiment_todos", [])),
        "next_meeting_focus": list(memory.get("next_meeting_focus", [])),
    }
    rows = section_map.get(normalized_section)
    if rows is None:
        return {
            "section": normalized_section,
            "ok": False,
            "error": (
                "Unknown section. Use one of: overview, full, meeting_window, "
                "action_items, method_changes, experiment_todos, next_meeting_focus."
            ),
        }

    page = rows[safe_offset : safe_offset + safe_limit]
    return {
        "section": normalized_section,
        "items": page,
        "offset": safe_offset,
        "limit": safe_limit,
        "returned_count": len(page),
        "total_count": len(rows),
        "has_more": safe_offset + len(page) < len(rows),
    }


def _extract_patch_sections(updated_memory: dict[str, Any]) -> list[str]:
    patch_sections: list[str] = []
    for key in WRITABLE_MEMORY_SECTIONS:
        if key in updated_memory:
            patch_sections.append(key)
    return patch_sections


def _content_snapshot(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "meeting_history_ids": list(memory.get("meeting_history_ids", [])),
        "meeting_window": list(memory.get("meeting_window", [])),
        "action_items": list(memory.get("action_items", [])),
        "method_changes": list(memory.get("method_changes", [])),
        "experiment_todos": list(memory.get("experiment_todos", [])),
        "next_meeting_focus": list(memory.get("next_meeting_focus", [])),
    }


def _summarize_patch_counts(updated_memory: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for section in _extract_patch_sections(updated_memory):
        value = updated_memory.get(section)
        if isinstance(value, list):
            counts[section] = len(value)
        elif value is None:
            counts[section] = 0
        else:
            counts[section] = 1
    return counts


def _record_memory_read(
    state: dict[str, Any],
    section: str,
    result: dict[str, Any],
) -> None:
    if section == "full":
        state["read_sections"].update(WRITABLE_MEMORY_SECTIONS)
        state["read_sections"].add("overview")
        state["fully_read_sections"].update(WRITABLE_MEMORY_SECTIONS)
        return

    if section not in WRITABLE_MEMORY_SECTIONS:
        return

    try:
        offset = int(result.get("offset", 0) or 0)
        returned_count = int(result.get("returned_count", 0) or 0)
        total_count = int(result.get("total_count", 0) or 0)
    except (TypeError, ValueError):
        return

    state["read_totals"][section] = total_count
    ranges = state["read_ranges"].setdefault(section, [])
    ranges.append((offset, offset + returned_count))
    if _ranges_cover_total(ranges, total_count):
        state["fully_read_sections"].add(section)


def _ranges_cover_total(ranges: list[tuple[int, int]], total_count: int) -> bool:
    if total_count <= 0:
        return True

    merged = sorted((max(start, 0), max(end, 0)) for start, end in ranges)
    covered_until = 0
    for start, end in merged:
        if end <= covered_until:
            continue
        if start > covered_until:
            return False
        covered_until = end
        if covered_until >= total_count:
            return True
    return covered_until >= total_count


def _section_fully_read(state: dict[str, Any], section: str) -> bool:
    return section in state.get("fully_read_sections", set())


def _record_transcript_overview_read(
    state: dict[str, Any],
    result: dict[str, Any],
) -> None:
    try:
        line_count = int(result.get("line_count", 0) or 0)
    except (AttributeError, TypeError, ValueError):
        return
    if line_count > 0:
        state["transcript_total_count"] = line_count


def _record_transcript_lines_read(
    state: dict[str, Any],
    result: dict[str, Any],
) -> None:
    if not isinstance(result, dict):
        state["transcript_read_count"] += 1
        return

    try:
        returned_count = int(result.get("returned_count", 0) or 0)
    except (TypeError, ValueError):
        returned_count = 0
    state["transcript_read_count"] += returned_count

    try:
        line_count = int(result.get("line_count", 0) or 0)
    except (TypeError, ValueError):
        line_count = 0
    if line_count > 0:
        state["transcript_total_count"] = line_count

    items = result.get("items")
    line_numbers: list[int] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                line_numbers.append(int(item.get("line_number", 0) or 0))
            except (TypeError, ValueError):
                continue

    if line_numbers:
        start = min(line_numbers)
        end = max(line_numbers)
    else:
        try:
            start = int(result.get("start_line", 0) or 0)
            end = int(result.get("end_line", 0) or 0)
        except (TypeError, ValueError):
            return
        if returned_count > 0:
            end = min(end, start + returned_count - 1)

    if start > 0 and end >= start:
        state["transcript_read_ranges"].append((start - 1, end))


def _transcript_fully_read(state: dict[str, Any]) -> bool:
    try:
        total_count = int(state.get("transcript_total_count", 0) or 0)
    except (TypeError, ValueError):
        total_count = 0
    if total_count <= 0:
        return False
    return _ranges_cover_total(state.get("transcript_read_ranges", []), total_count)


def _next_unread_transcript_line(state: dict[str, Any]) -> int:
    ranges = sorted(
        (max(start, 0), max(end, 0))
        for start, end in state.get("transcript_read_ranges", [])
    )
    covered_until = 0
    for start, end in ranges:
        if end <= covered_until:
            continue
        if start > covered_until:
            break
        covered_until = end
    return covered_until + 1


def _patch_adds_unknown_action_item(
    updated_memory: dict[str, Any],
    current_memory: dict[str, Any],
) -> bool:
    rows = updated_memory.get("action_items")
    if not isinstance(rows, list):
        return False

    existing_ids = {
        str(row.get("item_id", "")).strip()
        for row in current_memory.get("action_items", [])
        if isinstance(row, dict)
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("item_id", "")).strip()
        if not item_id or item_id not in existing_ids:
            return True
    return False


def generate_updated_memory(
    model_name: str,
    api_key: str,
    transcript: str,
    current_memory: dict[str, Any],
    meeting_id: str,
    source_file: str,
    transcript_line_count: int | None = None,
    on_transcript_overview_read: Callable[[], dict[str, Any]] | None = None,
    on_transcript_lines_read: (
        Callable[[int, int | None, int], dict[str, Any]] | None
    ) = None,
    on_memory_read: Callable[[], dict[str, Any]] | None = None,
    on_memory_write: Callable[[dict[str, Any]], None] | None = None,
    log_callback: Callable[[str], None] | None = None,
    max_tool_rounds: int | None = MAX_TOOL_ROUNDS,
    verbose: bool = True,
) -> dict[str, Any]:
    def log(message: str) -> None:
        line = f"[llm_update] {message}"
        if log_callback is not None:
            log_callback(line)
        elif verbose:
            print(line, flush=True)

    client = genai.Client(api_key=api_key)
    prompt = build_tool_call_prompt(
        meeting_id=meeting_id,
        source_file=source_file,
        transcript_line_count=(
            transcript_line_count
            if transcript_line_count is not None
            else len([line for line in transcript.splitlines() if line.strip()])
        ),
    )
    log(
        f"start model={model_name} meeting_id={meeting_id} "
        f"memory_version={int(current_memory.get('memory_version', 0) or 0)} "
        f"max_tool_rounds={max_tool_rounds if max_tool_rounds is not None else 'unlimited'}"
    )

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        log(f"attempt {attempt}/{MAX_GENERATION_ATTEMPTS}: creating tool-calling chat")
        state: dict[str, Any] = {
            "base_memory": current_memory,
            "latest_memory": current_memory,
            "target_memory_version": (
                int(current_memory.get("memory_version", 0) or 0) + 1
            ),
            "write_count": 0,
            "written_memory": None,
            "read_sections": set(),
            "read_ranges": {},
            "read_totals": {},
            "fully_read_sections": set(),
            "transcript_read_count": 0,
            "transcript_read_ranges": [],
            "transcript_total_count": int(transcript_line_count or 0),
            "transcript_finish_reminders": 0,
        }

        def read_transcript_overview() -> dict[str, Any]:
            """Read transcript metadata and a tiny head/tail preview from SQLite."""
            if on_transcript_overview_read is None:
                nonempty_lines = [
                    line.strip()
                    for line in transcript.splitlines()
                    if line.strip()
                ]
                result = {
                    "ok": True,
                    "meeting_id": meeting_id,
                    "source_file": source_file,
                    "line_count": len(nonempty_lines),
                    "first_lines": [
                        {
                            "line_number": index + 1,
                            "speaker": "",
                            "text": line,
                            "raw_line": line,
                        }
                        for index, line in enumerate(nonempty_lines[:3])
                    ],
                    "last_lines": [
                        {
                            "line_number": (
                                len(nonempty_lines)
                                - len(nonempty_lines[-3:])
                                + index
                                + 1
                            ),
                            "speaker": "",
                            "text": line,
                            "raw_line": line,
                        }
                        for index, line in enumerate(nonempty_lines[-3:])
                    ],
                }
                _record_transcript_overview_read(state, result)
                return result
            result = on_transcript_overview_read()
            _record_transcript_overview_read(state, result)
            return result

        def read_transcript_lines(
            start_line: int = 1,
            end_line: int = 0,
            limit: int = 30,
        ) -> dict[str, Any]:
            """Read a partial line range from the SQLite-backed transcript.

            Args:
                start_line: First transcript line to read, using 1-based line numbers.
                end_line: Last transcript line to read. Use 0 to let limit decide.
                limit: Maximum number of lines to return.
            """
            if on_transcript_lines_read is None:
                nonempty_lines = [
                    line.strip()
                    for line in transcript.splitlines()
                    if line.strip()
                ]
                safe_start = max(int(start_line or 1), 1)
                safe_limit = max(min(int(limit or 30), 80), 1)
                safe_end = (
                    int(end_line)
                    if int(end_line or 0) > 0
                    else safe_start + safe_limit - 1
                )
                safe_end = max(min(safe_end, safe_start + safe_limit - 1), safe_start)
                rows = nonempty_lines[safe_start - 1 : safe_end]
                result = {
                    "ok": True,
                    "meeting_id": meeting_id,
                    "start_line": safe_start,
                    "end_line": safe_end,
                    "returned_count": len(rows),
                    "line_count": len(nonempty_lines),
                    "has_more": safe_end < len(nonempty_lines),
                    "next_start_line": (
                        safe_end + 1 if safe_end < len(nonempty_lines) else None
                    ),
                    "items": [
                        {
                            "line_number": safe_start + index,
                            "speaker": "",
                            "text": line,
                            "raw_line": line,
                        }
                        for index, line in enumerate(rows)
                    ],
                }
                _record_transcript_lines_read(state, result)
                return result

            normalized_end_line = int(end_line or 0)
            result = on_transcript_lines_read(
                start_line,
                normalized_end_line if normalized_end_line > 0 else None,
                limit,
            )
            _record_transcript_lines_read(state, result)
            return result

        def read_short_term_memory(
            section: str = "overview",
            offset: int = 0,
            limit: int = DEFAULT_TOOL_PAGE_SIZE,
        ) -> dict[str, Any]:
            """Read short-term memory from SQLite-backed storage in small sections.

            Args:
                section: One of overview, full, meeting_window, action_items,
                    method_changes, experiment_todos, next_meeting_focus.
                    Default is overview.
                offset: Starting offset for paginated sections.
                limit: Maximum number of rows to return for paginated sections.
            """
            normalized_section = str(section or "overview").strip().lower()
            memory = (
                on_memory_read()
                if on_memory_read is not None
                else state["latest_memory"]
            )
            state["latest_memory"] = memory
            state["read_sections"].add(normalized_section)
            result = _slice_memory_section(
                memory=memory,
                section=normalized_section,
                offset=offset,
                limit=limit,
            )
            _record_memory_read(state, normalized_section, result)
            return result

        def write_short_term_memory(
            updated_memory: dict[str, Any],
            note: str = "",
        ) -> dict[str, Any]:
            """
            Persist one memory update patch.

            Args:
                updated_memory: Partial memory patch following the short-term schema.
                    Only include fields that actually changed.
                note: Optional explanation for this write.
            """
            if not isinstance(updated_memory, dict):
                return {
                    "ok": False,
                    "error": "updated_memory must be a JSON object.",
                }

            if int(state.get("transcript_read_count", 0) or 0) <= 0:
                return {
                    "ok": False,
                    "error": (
                        "Read transcript lines with read_transcript_lines before writing "
                        "memory, so every patch is grounded in transcript evidence."
                    ),
                }

            patch_sections = _extract_patch_sections(updated_memory)
            patch_counts = _summarize_patch_counts(updated_memory)
            log(
                "tool write_short_term_memory requested "
                f"patch_sections={patch_sections} "
                f"patch_counts={patch_counts}"
            )
            if not patch_sections:
                return {
                    "ok": False,
                    "error": (
                        "No writable memory sections provided. "
                        "Include one of: meeting_window, action_items, "
                        "method_changes, experiment_todos, next_meeting_focus."
                    ),
                }

            if len(patch_sections) > MAX_PATCH_SECTIONS_PER_WRITE:
                return {
                    "ok": False,
                    "error": (
                        "Too many top-level sections in one write. "
                        f"Max allowed is {MAX_PATCH_SECTIONS_PER_WRITE}; got {patch_sections}."
                    ),
                }

            missing_reads = [
                section
                for section in patch_sections
                if section in HEAVY_READ_REQUIRED_SECTIONS
                and section not in state["read_sections"]
            ]
            if missing_reads:
                return {
                    "ok": False,
                    "error": (
                        "Missing prerequisite read for sections: "
                        f"{missing_reads}. Read those sections first before writing."
                    ),
                }

            if "action_items" in patch_sections and _patch_adds_unknown_action_item(
                updated_memory,
                state["latest_memory"],
            ):
                current_action_count = len(
                    state["latest_memory"].get("action_items", [])
                )
                if (
                    current_action_count > DEFAULT_TOOL_PAGE_SIZE
                    and not _section_fully_read(state, "action_items")
                ):
                    return {
                        "ok": False,
                        "error": (
                            "Before adding a new/unknown action item when many action "
                            "items already exist, read the complete action_items section "
                            "with pagination so you can compare against existing IDs. "
                            f"Current count={current_action_count}; use offsets "
                            f"0, {DEFAULT_TOOL_PAGE_SIZE}, {DEFAULT_TOOL_PAGE_SIZE * 2}, "
                            "and continue until has_more=false."
                        ),
                    }

            normalized = normalize_memory(
                updated_memory=updated_memory,
                previous_memory=state["latest_memory"],
                meeting_id=meeting_id,
                source_file=source_file,
            )
            normalized["memory_version"] = state["target_memory_version"]
            if _content_snapshot(normalized) == _content_snapshot(state["latest_memory"]):
                return {
                    "ok": False,
                    "error": (
                        "No-op write detected. Read more context or submit a smaller patch "
                        "that changes memory content."
                    ),
                }
            log(
                "tool write_short_term_memory normalized "
                f"memory_version={normalized['memory_version']} "
                f"meeting_window={len(normalized.get('meeting_window', []))} "
                f"action_items={len(normalized.get('action_items', []))}"
            )

            if on_memory_write is not None:
                log("tool write_short_term_memory persisting to storage")
                on_memory_write(normalized)

            persisted_memory = on_memory_read() if on_memory_read is not None else normalized
            state["latest_memory"] = persisted_memory
            state["written_memory"] = persisted_memory
            state["write_count"] = int(state.get("write_count", 0) or 0) + 1

            return {
                "ok": True,
                "note": note,
                "write_count": state["write_count"],
                "memory_version": persisted_memory["memory_version"],
                "last_updated_meeting_id": persisted_memory["last_updated_meeting_id"],
                "meeting_window_ids": [
                    row.get("meeting_id", "")
                    for row in persisted_memory.get("meeting_window", [])
                ],
                "action_items_count": len(persisted_memory.get("action_items", [])),
            }

        config = types.GenerateContentConfig(
            system_instruction="你是嚴謹的短期記憶維護助手，必須先讀後寫，並只呼叫必要工具。",
            temperature=0.1,
            tools=[
                read_transcript_overview,
                read_transcript_lines,
                read_short_term_memory,
                write_short_term_memory,
            ],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="AUTO")
            ),
        )

        chat = client.chats.create(model=model_name, config=config)
        log("sending initial prompt to Gemini")
        response = _call_with_retry(
            lambda: chat.send_message(prompt),
            log=log,
            operation_name="tool-calling send_message initial",
        )

        round_index = 1
        while max_tool_rounds is None or round_index <= max_tool_rounds:
            function_calls = list(response.function_calls or [])
            if not function_calls:
                if not _transcript_fully_read(state):
                    state["transcript_finish_reminders"] += 1
                    if state["transcript_finish_reminders"] > 3:
                        raise RuntimeError(
                            "Gemini stopped before reading the full transcript."
                        )
                    next_line = _next_unread_transcript_line(state)
                    log(
                        f"round {round_index}: transcript not fully read; "
                        f"requesting continuation from line {next_line}"
                    )
                    response = _call_with_retry(
                        lambda: chat.send_message(
                            "你尚未讀完整份逐字稿，不能結束。"
                            f"請呼叫 read_transcript_lines 從第 {next_line} 行繼續讀，"
                            "直到 has_more=false，再做必要更新。"
                        ),
                        log=log,
                        operation_name="tool-calling send_message transcript continuation",
                    )
                    round_index += 1
                    continue
                log(f"round {round_index}: no tool call returned")
                break

            parts: list[types.Part] = []
            log(f"round {round_index}: {len(function_calls)} tool call(s)")
            for function_call in function_calls:
                tool_name = function_call.name or ""
                args = function_call.args or {}
                log(
                    f"round {round_index}: invoking tool={tool_name} "
                    f"args_keys={sorted(args.keys())} "
                    f"args={json.dumps(args, ensure_ascii=False, sort_keys=True)}"
                )

                if tool_name == "read_transcript_overview":
                    try:
                        tool_result = read_transcript_overview()
                    except TypeError as exc:
                        tool_result = {
                            "ok": False,
                            "error": f"Invalid tool args for read_transcript_overview: {exc}",
                        }
                elif tool_name == "read_transcript_lines":
                    try:
                        tool_result = read_transcript_lines(**args)
                    except (TypeError, ValueError) as exc:
                        tool_result = {
                            "ok": False,
                            "error": f"Invalid tool args for read_transcript_lines: {exc}",
                        }
                elif tool_name == "read_short_term_memory":
                    try:
                        tool_result = read_short_term_memory(**args)
                    except TypeError as exc:
                        tool_result = {
                            "ok": False,
                            "error": f"Invalid tool args for read_short_term_memory: {exc}",
                        }
                elif tool_name == "write_short_term_memory":
                    try:
                        tool_result = write_short_term_memory(**args)
                    except TypeError as exc:
                        tool_result = {
                            "ok": False,
                            "error": f"Invalid tool args for write_short_term_memory: {exc}",
                        }
                else:
                    tool_result = {"ok": False, "error": f"Unknown tool: {tool_name}"}

                parts.append(
                    types.Part.from_function_response(
                        name=tool_name,
                        response=tool_result,
                    )
                )

            log(f"round {round_index}: sending tool responses back to Gemini")
            response = _call_with_retry(
                lambda: chat.send_message(parts),
                log=log,
                operation_name=f"tool-calling send_message round {round_index}",
            )
            round_index += 1
        else:
            log(f"tool loop reached max_tool_rounds={max_tool_rounds}")

        written_memory = state.get("written_memory")
        if isinstance(written_memory, dict):
            log(
                "tool-calling update finished successfully "
                f"memory_version={written_memory['memory_version']}"
            )
            return written_memory

        raw_text = response.text or ""
        debug_path = save_failed_response(
            meeting_id=meeting_id,
            attempt=attempt,
            raw_text=raw_text,
            suffix="tool_call_no_write",
        )
        log(
            "tool-calling did not produce write call, "
            f"fallback to structured JSON mode (debug={debug_path})"
        )

        try:
            structured_update = _generate_structured_update(
                client=client,
                model_name=model_name,
                transcript=transcript,
                current_memory=current_memory,
                meeting_id=meeting_id,
                source_file=source_file,
                log=log,
            )
            normalized = normalize_memory(
                updated_memory=structured_update,
                previous_memory=current_memory,
                meeting_id=meeting_id,
                source_file=source_file,
            )
            if on_memory_write is not None:
                log("structured fallback persisting to storage")
                on_memory_write(normalized)
                normalized = (
                    on_memory_read() if on_memory_read is not None else normalized
                )
            log(
                "structured fallback succeeded "
                f"memory_version={normalized['memory_version']}"
            )
            return normalized
        except Exception as exc:  # noqa: BLE001
            log(f"structured fallback failed on attempt {attempt}: {exc}")
            if attempt >= MAX_GENERATION_ATTEMPTS:
                raise RuntimeError(
                    "Failed to update memory via tool calling and structured fallback. "
                    f"Last tool-response debug file: {debug_path}"
                ) from exc

    raise RuntimeError("Unreachable: generation attempts exhausted unexpectedly.")
