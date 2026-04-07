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
        "methodology": "",
        "core_values": [],
        "method_timeline": [],
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
            "description": "本階段的整體摘要（繁體中文）。",
        },
        "key_decisions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "本階段的關鍵決策列表。",
        },
        "method_evolution": {
            "type": "array",
            "description": "本階段的方法演進記錄，嚴格按時間順序排列。",
            "items": {
                "type": "object",
                "properties": {
                    "method": {"type": "string"},
                    "change": {"type": "string", "description": "變更內容描述"},
                    "reason": {"type": "string", "description": "變更原因"},
                    "meeting_id": {"type": "string"},
                },
                "required": ["method", "change", "reason", "meeting_id"],
                "additionalProperties": False,
            },
        },
        "unresolved_issues": {
            "type": "array",
            "items": {"type": "string"},
            "description": "本階段尚未解決的問題。",
        },
    },
    "required": ["summary", "key_decisions", "method_evolution", "unresolved_issues"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Gemini Structured Output: Project Profile Update (L2 → L3)
# ---------------------------------------------------------------------------
PROFILE_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "methodology": {
            "type": "string",
            "description": "目前確立的研究方法論概述。",
        },
        "core_values": {
            "type": "array",
            "items": {"type": "string"},
            "description": "研究計畫的核心價值觀與原則。",
        },
        "method_timeline": {
            "type": "array",
            "description": "方法論的完整時間軸演進，從最早到最新。",
            "items": {
                "type": "object",
                "properties": {
                    "period": {"type": "string"},
                    "method": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["adopted", "abandoned", "evolved"],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["period", "method", "status", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["methodology", "core_values", "method_timeline"],
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
