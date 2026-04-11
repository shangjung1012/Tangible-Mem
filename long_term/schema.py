from __future__ import annotations

from typing import Any

DEFAULT_MODEL_NAME = "gemini-2.5-flash"
EMBED_MODEL_NAME = "models/text-embedding-004"

MEMORY_OBJ_TYPES = {
    "decision",       # 會議中做出的決策或結論
    "todo",           # 被指派或提及的待辦事項
    "method_change",  # 方法論、演算法、流程的變更（因果鏈核心）
    "result",         # 實驗結果、發現、觀察報告
    "open_question",  # 尚未解決的研究問題
    "argument",       # 決策背後的論點與推理
}

# ---------------------------------------------------------------------------
# Default empty tree
# ---------------------------------------------------------------------------
DEFAULT_TREE: dict[str, Any] = {
    "tree_version": 0,
    "last_updated_utc": "",
    "project_profile": {
        "project_id": "",
        "time_range": {"start": "", "end": ""},
        "core_goal": "",
        "current_phase": "",
        "established_methods": [],
        "long_term_open_questions": [],
        "child_phase_ids": [],
    },
    "phases": [],
    # meeting node schema (reference):
    # {
    #   "meeting_id": str,
    #   "timestamp": str,     # buildtime (system write time)
    #   "meeting_date": str,  # real meeting date for recency scoring
    #   "source_file": str,
    #   "phase_id": str,
    #   "memory_objects": list[dict],
    # }
    "meetings": [],
}

# ---------------------------------------------------------------------------
# Gemini Structured Output: Bridge (extract L1 memory objects)
# ---------------------------------------------------------------------------
BRIDGE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "memory_objects": {
            "type": "array",
            "description": "從逐字稿中擷取的記憶物件清單。",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": sorted(MEMORY_OBJ_TYPES),
                        "description": (
                            "decision=決議, todo=待辦, "
                            "method_change=方法變更, result=實驗結果或發現, "
                            "open_question=尚未解決的研究問題, "
                            "argument=決策背後的論點與推理"
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "記憶內容的簡要描述（繁體中文）。",
                    },
                    "importance": {
                        "type": "number",
                        "description": "重要性分數 0.0~1.0，1.0 為最重要。",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "從逐字稿中擷取的支持證據（可引用原文短句）。",
                    },
                    "related_topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "相關主題關鍵字，用於後續因果鏈追蹤。",
                    },
                },
                "required": ["type", "content", "importance", "evidence", "related_topics"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["memory_objects"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Gemini Structured Output: Phase Summary (L1 → L2)
# ---------------------------------------------------------------------------
PHASE_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": (
                "本階段的主軸描述，限 1-2 句，60 字以內（繁體中文）。"
                "只寫這段期間發生了什麼主要事情，不要列舉細節。"
            ),
        },
        "changes": {
            "type": "array",
            "description": (
                "本階段的淨方法變化，最多 5 條。"
                "只寫跨越整個 phase 後的淨結果，不要每個小調整都列出。"
                "每條 method 限 30 字以內。"
            ),
            "items": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["adopted", "abandoned", "evolved"],
                        "description": "adopted=本期確立, abandoned=本期棄用, evolved=持續演進中",
                    },
                    "method": {
                        "type": "string",
                        "description": "方法變化的一句話描述，30 字以內，不含 reason。",
                    },
                },
                "required": ["status", "method"],
                "additionalProperties": False,
            },
            "maxItems": 5,
        },
        "open_to_next": {
            "type": "array",
            "description": (
                "本階段結束時仍懸而未決、需要下一階段處理的問題，最多 2 條，每條 40 字以內。"
                "不要把所有 todo 都列入，只保留真正影響下一步進展的懸案。"
            ),
            "items": {"type": "string"},
            "maxItems": 2,
        },
    },
    "required": ["summary", "changes", "open_to_next"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Gemini Structured Output: Project Profile Update (L2 → L3)
# ---------------------------------------------------------------------------
PROFILE_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "core_goal": {
            "type": "string",
            "description": (
                "整個專案的核心目標，1-2 句，60 字以內（繁體中文）。"
                "回答「這個專案在做什麼、最終目的是什麼」，不要描述方法細節。"
            ),
        },
        "current_phase": {
            "type": "string",
            "description": (
                "目前整個研究所處的大階段，1 句，30 字以內。"
                "例如：「錄音系統穩定化與轉錄流程建立」。"
            ),
        },
        "established_methods": {
            "type": "array",
            "description": (
                "目前已確立並持續使用的核心做法，最多 5 條，每條 35 字以內。"
                "只列跨越多個 phase 都沒有變動的穩定做法，不要列每個 phase 的微調。"
                "已棄用的方法不要列入。"
            ),
            "items": {"type": "string"},
            "maxItems": 5,
        },
        "long_term_open_questions": {
            "type": "array",
            "description": (
                "從多個 phase 看下來，至今仍懸而未決的長期問題，最多 3 條，每條 40 字以內。"
                "只保留真正橫跨多個階段、影響整個研究方向的問題，不要列近期的 todo。"
            ),
            "items": {"type": "string"},
            "maxItems": 3,
        },
    },
    "required": [
        "core_goal",
        "current_phase",
        "established_methods",
        "long_term_open_questions",
    ],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Gemini Structured Output: Recall Planner
# ---------------------------------------------------------------------------
RECALL_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "complexity": {
            "type": "string",
            "enum": ["simple", "complex"],
            "description": (
                "simple=執行型問題（找最近的 TODO / Decision）, "
                "complex=演進型問題（需要時間軸追溯）"
            ),
        },
        "reasoning": {
            "type": "string",
            "description": "判斷理由。",
        },
        "search_targets": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["short_term", "long_term_l1", "long_term_l2", "long_term_l3"],
            },
            "description": "應搜尋的記憶層級。",
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "搜尋關鍵字。",
        },
        "time_range_hint": {
            "type": "string",
            "description": (
                "建議的時間範圍描述（如 '最近一個月'、'2026-01 到 2026-03'），"
                "若無特定範圍則留空字串。"
            ),
        },
    },
    "required": [
        "complexity",
        "reasoning",
        "search_targets",
        "keywords",
        "time_range_hint",
    ],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Gemini Structured Output: Recall Gate (filter)
# ---------------------------------------------------------------------------
RECALL_GATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relevant_obj_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "與問題相關的記憶物件 ID 列表。",
        },
        "reasoning": {"type": "string"},
    },
    "required": ["relevant_obj_ids", "reasoning"],
    "additionalProperties": False,
}
