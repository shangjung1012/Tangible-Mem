"""Build the active long_term L2 view from canonical share_mem L1 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from share_mem.store import iter_l1_objects, iter_meetings, load_share_tree, normalize_share_tree

L2_VIEW_SCHEMA_VERSION = 1
L2_VIEW_FILE_NAME = "l2_view.json"
L2_INDEX_FILE_NAME = "l2_index.json"
L2_MANIFEST_FILE_NAME = "manifest.json"
L2_UPDATES_DIR_NAME = "l2_updates"
L2_UNLINKED_FILE_NAME = "unlinked_l1_report.json"
L2_RESEARCH_LOGS_DIR_NAME = "l2_research_logs"
SUPPORTED_L2_MODES = {"deterministic", "hybrid"}

TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
SLUG_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)

GENERIC_LABELS = {
    "memory",
    "system",
    "architecture",
    "design",
    "topic",
    "topic tree",
    "topic-tree",
    "data",
    "evaluation",
}

TYPE_LIKE_LABELS = {
    "action item",
    "action_item",
    "approach change",
    "approach_change",
    "argument",
    "decision",
    "design decision",
    "finding",
    "method change",
    "method_change",
    "open issue",
    "open_issue",
    "open question",
    "open_question",
    "proposal",
    "result",
    "todo",
}

RELATED_TOPIC_CANONICAL_LABELS = {
    "alternative approaches": "alternative approaches",
    "data handling": "transcript segmentation and idea-unit coverage",
    "data management": "transcript segmentation and idea-unit coverage",
    "dataset acquisition": "dataset selection",
    "dataset selection": "dataset selection",
    "development workflow": "development workflow",
    "experimental setup": "research methodology",
    "literature review": "research methodology",
    "long term memory": "stm ltm integration",
    "long term memory architecture": "memory processing architecture",
    "long term memory implementation": "memory system implementation",
    "memory model": "memory processing architecture",
    "memory retrieval": "memory retrieval",
    "memory system architecture": "memory processing architecture",
    "memory system implementation": "memory system implementation",
    "memory system performance": "memory evaluation strategy",
    "output quality": "transcript segmentation and idea-unit coverage",
    "research methodology": "research methodology",
    "system architecture": "agentic pipeline control",
}
RELATED_TOPIC_FALLBACK_MIN_IMPORTANCE = 0.68

ADMINISTRATIVE_HINTS = (
    "meeting room",
    "meeting setup",
    "setup detail",
    "local aside",
    "briefly noted",
    "no long-term memory relevance",
    "api budget",
    "api usage",
    "api cost",
    "expense reimbursement",
    "academia sinica internship",
    "internship application",
    "resume and transcript",
    "api 預算",
    "api 的使用情況",
    "api 使用情況",
)

PRIORITY_CONCEPT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "research methodology",
        (
            "external paper",
            "reference paper",
            "literature review",
            "reviewed and dismissed",
            "not applicable",
            "評估了一篇",
            "外部論文",
            "參考論文",
            "不適用",
            "長上下文處理",
        ),
    ),
    (
        "stm ltm integration",
        (
            "保留短期記憶",
            "統一存入長期記憶",
            "短期記憶轉移到長期記憶",
            "短期記憶（stm）",
            "長期記憶（ltm）",
            "stm）而非",
            "ltm）結構",
        ),
    ),
    (
        "memory evidence anchoring",
        (
            "specific audio timestamps",
            "specific timestamp",
            "audio timestamp",
            "audio timestamps",
            "source link",
            "transcript chunk",
            "audio/video file",
            "play back the original recording",
            "original recording segment",
            "original meeting segment",
            "verifying the ai's memory recall",
            "verifying ai recalled memories",
            "manual verification process",
            "manually assess its relevance",
            "relevance is assessed",
            "inspect the source",
            "source material",
            "link back to the original",
        ),
    ),
    (
        "data fragmentation",
        (
            "fragmented",
            "fragmentation",
            "simplistic",
            "records are omitted",
            "information to be skipped",
            "過於零碎",
            "零碎",
            "過於簡單",
            "未能記錄資訊",
            "找不到關聯",
        ),
    ),
    (
        "memory evaluation strategy",
        (
            "memo",
            "locomo",
            "multi-hop",
            "multi hop",
            "llm-as-judge",
            "llm as judge",
            "unanswerable question",
            "unanswerable questions",
            "無法回答的問題",
            "模型處理無法",
            "查詢能力",
            "evaluation plan",
            "compare three long-term memory update strategies",
            "long-term memory update strategies",
            "fixed chunking",
            "iterative merging",
            "incremental method",
            "experiment postponed",
            "ablation study",
            "baselines",
            "rag-only",
            "short-term-only",
            "long-term-only",
            "standard answer",
            "standard answers",
            "measure correctness",
            "評估計劃",
            "評估標準",
            "標準答案",
            "衡量正確性",
            "長期演變",
            "決策推理",
        ),
    ),
    (
        "memory update semantics",
        (
            "dynamic time tracking",
            "temporal reference",
            "relative time",
            "time reference",
            "time references",
            "this meeting",
            "one week ago",
            "meeting id",
            "meeting ids",
            "動態時間追蹤",
            "本次會議",
            "一週前",
            "時間參考",
            "相對時間",
            "會議id",
            "時間軸",
        ),
    ),
    (
        "agentic pipeline control",
        (
            "manager-agent",
            "manager agent",
            "manager-agent architecture",
            "central manager",
            "pure dispatcher",
            "dispatcher",
            "delegating tasks",
            "specialized worker agents",
            "worker agents",
            "separate agent",
            "manager waits",
            "tool calling",
            "tool-calling",
            "function calling",
            "monolithic process",
            "code-driven architecture",
            "main workflow",
            "application's logic",
            "specific sub-tasks",
            "fixed flow",
            "single-prompt approach",
            "multi-agent architecture",
            "refactor the system",
            "external code",
            "programmatic control",
            "sequential agent processing",
            "shared blackboard",
            "blackboard architecture",
            "多個專門的 agent",
            "多個 agent",
            "重複的 candidate",
            "平行地",
            "比對、區分或合併",
            "llm 主導控制流程",
            "控制流程",
            "函數調用",
            "狀態管理",
            "prompt 明確指示",
        ),
    ),
    (
        "memory lifecycle",
        (
            "human-in-the-loop tuning",
            "importance tuning",
            "importance increase",
            "importance threshold",
            "importance score",
            "importance level",
            "initial importance",
            "memory unit",
            "frequency of mention",
            "discussion density",
            "stored in long-term memory",
            "discussed intensely",
            "short period",
            "mentioned again",
            "mentioned multiple times",
            "related idea units",
            "user adjusts",
            "inspect and adjust",
            "adjust scores",
            "tuning memory node importance",
            "forgetting",
            "fade out",
            "old, irrelevant topics",
            "outdated information",
            "non-active information",
            "inactive information",
            "淡化",
            "非活躍",
            "不相關長期資訊",
            "decay",
        ),
    ),
    (
        "memory processing architecture",
        (
            "three-tier hierarchical",
            "three tier hierarchical",
            "three-tier hierarchy",
            "three tier hierarchy",
            "l1 nodes",
            "l2 nodes",
            "l3 nodes",
            "highest-level summary",
            "memory hierarchy",
            "hierarchical memory",
            "time-based model",
            "time based model",
            "topic-based model",
            "topic based model",
            "time-based hierarchy",
            "topic-based hierarchy",
            "relationships between memory stores",
            "update rules and the relationships",
            "define the long-term memory architecture",
            "時間導向",
            "主題導向",
            "時間模型",
            "主題模型",
            "時間結構",
            "主題結構",
            "語義主題",
            "會議時間順序",
        ),
    ),
    (
        "memory retrieval",
        (
            "retriever",
            "retrieve information",
            "memory stores",
            "access short-term",
            "access long-term",
            "filtering step",
            "initial filtering",
            "data retrieval process",
            "retrieve phase",
            "retrieval phase",
            "retrieval strategy",
            "memory retrieval",
            "查詢內容",
            "決定使用哪種記憶體",
            "使用哪種記憶體",
            "短期記憶體",
            "長期記憶體",
            "先搜尋",
            "放大",
            "篩選",
            "檢索",
        ),
    ),
    (
        "memory system implementation",
        (
            "user-configurable",
            "configurable parameter",
            "memory categories",
            "extraction categories",
            "記憶類別",
            "可由使用者配置",
            "自行定義",
            "重要資訊類型",
        ),
    ),
    (
        "stm ltm integration",
        (
            "stm-ltm",
            "stm ltm",
            "short-term memory and long-term memory",
            "short term memory and long term memory",
            "short-term and long-term",
            "short term and long term",
            "短期記憶」和「長期記憶",
            "短期記憶和長期記憶",
        ),
    ),
    (
        "dataset selection",
        (
            "dataset selection",
            "dataset sufficiency",
            "dataset consists",
            "meeting data is sufficient",
            "data is sufficient",
            "accumulated 180 minutes",
            "180 minutes of meeting data",
            "180 minutes of audio",
            "5 meetings",
            "transcripts have quality issues",
            "overlapping speech",
            "manual correction",
            "automatic speech recognition",
            "asr",
            "meeting summarization",
            "prior use in academic research",
            "established value",
            "reference papers",
            "5次會議",
            "約180分鐘",
            "數據量",
            "數據不足",
            "擴增數據",
            "資料量",
            "資料不足",
            "資料擴增",
            "icsi",
            "corpus",
            "token count",
            "data augmentation",
            "meeting recordings",
            "資料集",
            "語料庫",
            "數據不足",
            "數據增強",
            "縱向數據集",
            "會議摘要",
        ),
    ),
    (
        "l2 topic grouping",
        (
            "層級式資料結構",
            "資料的層級結構",
            "idea units、segments、topics",
            "idea units、segments",
            "更高級別分組",
            "更大的 topic",
            "多個 segment",
            "topic 之下",
        ),
    ),
    (
        "transcript segmentation and idea-unit coverage",
        (
            "句子分組",
            "想法單元",
            "將其合併",
            "可變大小的輸出",
            "文本分割",
            "分割策略",
            "會議記錄",
            "逐字稿",
            "文本區塊",
            "固定大小的區塊",
            "約20行文本區塊",
            "動態分塊",
            "逐句處理",
            "讀取文本",
            "起訖行數",
            "讀取區塊重疊",
            "文本分塊處理",
        ),
    ),
    (
        "l2 topic grouping",
        (
            "objects）和議題",
            "物件（objects）",
            "議題（issues）",
            "兩層式架構",
            "追蹤重複出現的話題",
            "物件可以連結到多個議題",
            "object can link to multiple issues",
            "objects and issues",
        ),
    ),
    (
        "prompt design and instruction quality",
        (
            "prompt engineering",
            "system prompts",
            "important prompts",
            "self-contained",
            "avoid jargon",
            "downstream l1 agents",
            "agent itself would not understand",
            "unreliable outputs",
            "refine them to be more generic",
            "prompts should be more generic",
            "generic prompt",
            "generic prompts",
            "internal project jargon",
            "l1 agent",
            "model's comprehension",
            "generalizability",
        ),
    ),
    (
        "pipeline observability and validation",
        (
            "black box",
            "single-prompt",
            "uncontrollable",
            "unobservable",
            "fails to follow instructions",
            "internal state",
            "intermediate outputs",
            "cannot be inspected",
            "cannot inspect",
            "log every prompt",
            "corresponding result",
            "agent interaction",
            "step-by-step verification",
            "full prompt",
            "returned result",
            "input and output",
            "驗證流程",
            "完整 prompt",
            "返回的 result",
            "輸入與輸出",
            "追蹤和檢查",
            "各步驟的合理性",
        ),
    ),
)

CONCEPT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "transcript segmentation and idea-unit coverage",
        (
            "idea unit",
            "idea units",
            "segment",
            "segments",
            "segmentation",
            "chunk",
            "chunks",
            "chunking",
            "fixed chunk",
            "fixed chunk size",
            "dynamic chunking",
            "adaptive window",
            "transcript processing",
            "preprocess meeting records",
            "pre-process",
            "pre-processing",
            "finer-grained units",
            "misses transcript lines",
            "gaps",
            "repair mechanism",
            "boundary repair",
            "segment boundary",
            "segment boundaries",
            "split across",
            "cross chunk",
            "global vector",
            "non-adjacent ideas",
            "generated nodes",
            "single-pass approach",
            "iterative method",
        ),
    ),
    (
        "agentic pipeline control",
        (
            "manager-agent",
            "manager agent",
            "multi-agent",
            "agent-based",
            "separate agent",
            "agent response",
            "manager waits",
            "central manager",
            "dispatcher",
            "delegating tasks",
            "swappable agents",
            "tool calling",
            "tool-calling",
            "function calling",
            "control flow",
            "external code",
            "external program",
            "programmatic control",
            "boolean variable",
            "next unprocessed sentence",
            "transcript overview",
            "total line count",
            "content preview",
            "input size",
            "overloaded manager",
            "specialized agent model",
            "task-specific agent",
            "manager memory",
            "manager's memory",
            "manager memory from becoming cluttered",
            "encapsulated",
            "encapsulates its own knowledge",
        ),
    ),
    (
        "pipeline observability and validation",
        (
            "verification workflow",
            "validation workflow",
            "驗證流程",
            "records each agent step",
            "full prompt",
            "完整 prompt",
            "returned result",
            "返回的 result",
            "input and output",
            "輸入與輸出",
            "trace",
            "traced",
            "追蹤",
            "檢查",
            "observability",
            "visibility",
            "checkpoint",
            "checkpoints",
            "intermediate result",
            "intermediate output",
            "debugging",
            "single-pass",
            "single pass",
            "lack of control",
            "opacity",
            "multi-step",
            "externally controlled workflow",
            "external checking",
            "test individual components",
            "components in isolation",
            "cascading errors",
            "cascading effects",
            "difficult to debug",
        ),
    ),
    (
        "memory evidence anchoring",
        (
            "source link",
            "audio timestamp",
            "original recording",
            "original source",
            "original source material",
            "raw recording",
            "recording data",
            "evidence quote",
            "grounding",
            "source file",
            "link back",
        ),
    ),
    (
        "data fragmentation",
        (
            "fragment",
            "fragmented",
            "fragmentation",
            "chunk",
            "fixed chunk",
            "segment boundary",
            "boundary repair",
            "segment boundaries",
            "split across",
            "cross chunk",
            "simplistic",
            "relationship logs",
            "records are omitted",
            "information to be skipped",
            "瑣碎",
            "漏掉",
        ),
    ),
    (
        "memory update semantics",
        (
            "dynamic time tracking",
            "this meeting",
            "one week ago",
            "meeting id",
            "meeting ids",
            "relative time",
            "temporal reference",
            "time tracking",
            "memory entry",
            "memory items are tracked",
            "item is mentioned again",
            "subsequent meeting discusses",
            "generate summaries and action items",
            "memory update process",
            "記憶更新過程",
            "update function",
            "update memory nodes",
            "updating memory nodes",
            "correct memory node",
            "multiple memory nodes",
            "updating a memory node",
            "更新特定的記憶節點",
            "filter relevant input",
            "選擇相關句子",
            "逐步演練",
            "information bleeding",
            "contaminate distinct nodes",
            "update methods",
            "update method",
            "時間軸",
            "會議id",
            "當前會議",
            "後續會議",
            "記憶條目",
            "更新相應的記憶",
        ),
    ),
    (
        "memory retrieval",
        (
            "retrieve phase",
            "retrieve' phase",
            "retrieval phase",
            "retrieval component",
            "retrieval strategy",
            "recalling information",
            "distance for recalling",
            "recall distance",
            "memory retrieval",
            "can be recalled",
            "what can be recalled",
            "beyond three sessions",
            "more than three sessions",
            "取用",
            "檢索",
        ),
    ),
    (
        "memory evaluation strategy",
        (
            "memo",
            "locomo",
            "multi-hop",
            "multi hop",
            "llm-as-judge",
            "llm as judge",
            "benchmark",
            "benchmarking",
            "evaluate",
            "evaluating",
            "evaluation",
            "precision/recall",
            "precision and recall",
            "precision-recall",
            "ground truth",
            "gold",
            "unanswerable question",
            "unanswerable questions",
            "standardized test",
            "standardized tests",
            "model performance",
            "proving its superiority",
            "prove its necessity",
        ),
    ),
    (
        "memory lifecycle",
        (
            "discard as l1",
            "discard-as-l1",
            "discard",
            "importance threshold",
            "importance score",
            "importance tuning",
            "tuning memory node importance",
            "inspect and adjust scores",
            "suggests related units",
            "forgetting",
            "decay",
            "activation",
            "lifecycle",
            "unlinked",
            "skip l1",
        ),
    ),
    (
        "project demo strategy",
        (
            "minimum viable architecture",
            "full paper replication",
            "not full replication",
            "copying the whole paper",
            "added value",
            "demonstrates different agent behavior",
            "agent behavior",
            "human interaction",
            "perception",
            "demo strategy",
            "demonstration strategy",
            "memory-enhanced agent",
            "standard llm",
            "open-source code",
            "open source code",
            "highlight",
            "show the added value",
            "展示",
            "附加價值",
            "複製論文",
            "代理行為",
        ),
    ),
    (
        "stm ltm integration",
        (
            "short-term memory",
            "short term memory",
            "last three sessions",
            "stm",
            "ltm",
            "short-term and long-term",
            "short term and long term",
        ),
    ),
    (
        "memory processing architecture",
        (
            "hierarchical memory",
            "memory hierarchy",
            "time-based model",
            "topic-based model",
            "topic based model",
            "time based model",
            "topic-based hierarchy",
            "memory hierarchy models",
            "bottom-up",
            "top-down",
            "top down",
            "parent-chain",
            "parent chain",
            "l1 to l2",
            "l1, l2",
            "l1 retrieval",
            "l2 context",
            "l3 context",
            "rag processing",
            "processing architecture",
            "memory architecture",
        ),
    ),
    (
        "l2 topic grouping",
        (
            "topic cluster",
            "l2 topic",
            "topic grouping",
            "topic node",
            "topic-tree",
            "topic tree",
        ),
    ),
)


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_hash(data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _slug(text: str, *, fallback: str = "l2") -> str:
    slug = SLUG_RE.sub("-", text.lower()).strip("-")
    return slug or fallback


def _clean_text(text: str, *, limit: int = 220) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _obj_text(obj: dict[str, Any]) -> str:
    topics = obj.get("related_topics", [])
    topic_text = " ".join(str(topic) for topic in topics) if isinstance(topics, list) else ""
    return " ".join(
        part
        for part in (
            str(obj.get("content", "") or ""),
            str(obj.get("evidence", "") or ""),
            topic_text,
        )
        if part
    )


def _importance(obj: dict[str, Any]) -> float:
    try:
        return float(obj.get("importance", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _is_administrative(obj: dict[str, Any]) -> bool:
    text = _obj_text(obj).lower()
    return any(hint in text for hint in ADMINISTRATIVE_HINTS)


def _hint_matches(text: str, hint: str) -> bool:
    if not hint:
        return False
    start_boundary = r"(?<![a-z0-9])" if hint[0].isalnum() else ""
    end_boundary = r"(?![a-z0-9])" if hint[-1].isalnum() else ""
    return re.search(f"{start_boundary}{re.escape(hint)}{end_boundary}", text) is not None


def _concept_label(obj: dict[str, Any]) -> tuple[str | None, str]:
    primary_text = str(obj.get("content", "") or "").lower()
    for label, hints in (*PRIORITY_CONCEPT_RULES, *CONCEPT_RULES):
        if any(_hint_matches(primary_text, hint) for hint in hints):
            return label, "concept_rule"
    return None, "no_concept"


def _topic_label_fallback(obj: dict[str, Any]) -> tuple[str | None, str]:
    topics = obj.get("related_topics", [])
    if not isinstance(topics, list):
        return None, "no_topic_fallback"
    for raw in topics:
        label = str(raw or "").replace("_", " ").replace("-", " ").strip().lower()
        if not label or label in GENERIC_LABELS or label in TYPE_LIKE_LABELS:
            continue
        canonical = RELATED_TOPIC_CANONICAL_LABELS.get(label)
        if not canonical:
            continue
        return canonical, "related_topic_fallback"
    return None, "no_topic_fallback"


def choose_l2_assignment(obj: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic L2 assignment or skip decision for one L1 object."""
    importance = _importance(obj)
    obj_type = str(obj.get("type", "") or "")
    if _is_administrative(obj):
        return {
            "action": "skip_l1",
            "reason": "administrative_or_local_context",
            "review_required": False,
            "confidence": 0.78,
        }

    label, reason = _concept_label(obj)
    if label is None:
        label, reason = _topic_label_fallback(obj)

    if label is None:
        return {
            "action": "skip_l1",
            "reason": "no_durable_l2_concept",
            "review_required": importance >= 0.7,
            "confidence": 0.64,
        }

    if reason == "related_topic_fallback" and importance < RELATED_TOPIC_FALLBACK_MIN_IMPORTANCE:
        return {
            "action": "skip_l1",
            "reason": "related_topic_below_l2_threshold",
            "review_required": False,
            "confidence": 0.68,
        }

    durable_type = obj_type in {
        "decision",
        "action_item",
        "todo",
        "open_issue",
        "open_question",
        "approach_change",
        "method_change",
        "proposal",
        "finding",
        "result",
        "argument",
    }
    if importance < 0.55 and not durable_type:
        return {
            "action": "skip_l1",
            "reason": "below_l2_importance_threshold",
            "review_required": False,
            "confidence": 0.7,
        }

    return {
        "action": "assign_l2",
        "l2_label": label,
        "reason": reason,
        "review_required": False,
        "confidence": round(min(0.95, 0.62 + importance * 0.28), 3),
    }


def empty_l2_view(*, source_tree_hash: str = "") -> dict[str, Any]:
    return {
        "schema_version": L2_VIEW_SCHEMA_VERSION,
        "generated_at_utc": "",
        "source": "share_mem",
        "source_tree_hash": source_tree_hash,
        "l2_nodes": [],
    }


def load_l2_view(root: Path | str) -> dict[str, Any]:
    path = Path(root) / L2_VIEW_FILE_NAME
    if not path.exists():
        return empty_l2_view()
    data = _load_json(path)
    if not isinstance(data, dict):
        raise RuntimeError(f"L2 view must be a JSON object: {path}")
    return data


def load_l2_index(root: Path | str) -> dict[str, Any]:
    path = Path(root) / L2_INDEX_FILE_NAME
    if not path.exists():
        return {}
    data = _load_json(path)
    if not isinstance(data, dict):
        raise RuntimeError(f"L2 index must be a JSON object: {path}")
    return data


def load_share_mem_l1_tree(share_mem_root: Path | str) -> dict[str, Any]:
    root = Path(share_mem_root)
    tree = load_share_tree(root)
    if list(iter_meetings(tree)):
        return tree

    meetings_dir = root / "meetings"
    meetings: list[dict[str, Any]] = []
    if meetings_dir.exists():
        for path in sorted(meetings_dir.glob("*.json")):
            data = _load_json(path)
            if isinstance(data, dict):
                meetings.append(data)
    return normalize_share_tree(
        {
            "tree_version": 0,
            "last_updated_utc": "",
            "project_profile": {},
            "phases": [],
            "meetings": meetings,
        }
    )


def clean_l2_outputs(output_root: Path | str) -> None:
    root = Path(output_root)
    for file_name in (L2_VIEW_FILE_NAME, L2_INDEX_FILE_NAME, L2_MANIFEST_FILE_NAME, L2_UNLINKED_FILE_NAME):
        path = root / file_name
        if path.exists():
            path.unlink()
    for dir_name in (L2_UPDATES_DIR_NAME, L2_RESEARCH_LOGS_DIR_NAME, "validation"):
        path = root / dir_name
        if path.exists():
            shutil.rmtree(path)


def _event_id(meeting_id: str, index: int) -> str:
    return f"L2E-{meeting_id}-{index:03d}"


def _build_l2_node(label: str, linked: list[dict[str, Any]]) -> dict[str, Any]:
    meeting_ids = sorted({str(item["meeting"].get("meeting_id", "") or "") for item in linked})
    timeline = [
        {
            "meeting_id": str(item["meeting"].get("meeting_id", "") or ""),
            "meeting_date": str(item["meeting"].get("meeting_date", "") or ""),
            "obj_id": str(item["obj"].get("obj_id", "") or ""),
            "summary": _clean_text(item["obj"].get("content", ""), limit=180),
        }
        for item in linked
    ]
    latest = timeline[-1]["summary"] if timeline else ""
    avg_confidence = (
        sum(float(item["assignment"].get("confidence", 0.0)) for item in linked) / len(linked)
        if linked
        else 0.0
    )
    return {
        "l2_id": f"L2-{_slug(label)}",
        "label": label,
        "source": "long_term_l2",
        "current_state": (
            f"This L2 topic has {len(linked)} linked L1 evidence objects across "
            f"{len(meeting_ids)} meeting(s). Latest evidence: {latest}"
        ),
        "timeline_digest": timeline,
        "linked_obj_ids": [str(item["obj"].get("obj_id", "") or "") for item in linked],
        "meeting_ids": meeting_ids,
        "event_count": len(linked),
        "confidence": round(avg_confidence, 3),
        "last_updated_meeting_id": str(linked[-1]["meeting"].get("meeting_id", "") or "") if linked else "",
    }


def _build_outputs(
    *,
    tree: dict[str, Any],
    share_mem_root: Path,
    output_root: Path,
    mode: str,
) -> dict[str, Any]:
    source_tree_hash = stable_hash(tree)
    linked_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    l2_index: dict[str, dict[str, Any]] = {}
    unlinked_objects: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []
    updates_by_meeting: dict[str, dict[str, Any]] = {}
    source_l1_count = 0

    for meeting in iter_meetings(tree):
        meeting_id = str(meeting.get("meeting_id", "") or "")
        meeting_events: list[dict[str, Any]] = []
        for ordinal, obj in enumerate(meeting.get("memory_objects", []), start=1):
            if not isinstance(obj, dict) or not str(obj.get("obj_id", "") or "").strip():
                continue
            source_l1_count += 1
            obj_id = str(obj.get("obj_id", "") or "")
            assignment = choose_l2_assignment(obj)
            event = {
                "event_id": _event_id(meeting_id, ordinal),
                "meeting_id": meeting_id,
                "obj_id": obj_id,
                "source_l1_type": str(obj.get("type", "") or ""),
                "importance": _importance(obj),
                "action": assignment["action"],
                "reason": assignment.get("reason", ""),
                "confidence": assignment.get("confidence", 0.0),
            }
            if assignment["action"] == "assign_l2":
                label = str(assignment["l2_label"])
                l2_id = f"L2-{_slug(label)}"
                action = "assign_existing" if linked_by_label[label] else "new_l2"
                event.update(
                    {
                        "action": action,
                        "l2_id": l2_id,
                        "l2_label": label,
                    }
                )
                linked_by_label[label].append(
                    {
                        "meeting": meeting,
                        "obj": obj,
                        "assignment": assignment,
                        "event_id": event["event_id"],
                    }
                )
                l2_index[obj_id] = {
                    "obj_id": obj_id,
                    "meeting_id": meeting_id,
                    "meeting_date": str(meeting.get("meeting_date", "") or ""),
                    "l2_id": l2_id,
                    "l2_label": label,
                    "source": "long_term_l2",
                    "event_id": event["event_id"],
                    "confidence": assignment.get("confidence", 0.0),
                    "assignment_reason": assignment.get("reason", ""),
                }
            else:
                skipped = {
                    "obj_id": obj_id,
                    "meeting_id": meeting_id,
                    "meeting_date": str(meeting.get("meeting_date", "") or ""),
                    "type": str(obj.get("type", "") or ""),
                    "importance": _importance(obj),
                    "content": _clean_text(obj.get("content", ""), limit=220),
                    "reason": assignment.get("reason", ""),
                    "review_required": bool(assignment.get("review_required", False)),
                }
                unlinked_objects.append(skipped)
                if skipped["review_required"]:
                    review_queue.append(skipped)
            meeting_events.append(event)
        updates_by_meeting[meeting_id] = {
            "schema_version": L2_VIEW_SCHEMA_VERSION,
            "meeting_id": meeting_id,
            "meeting_date": str(meeting.get("meeting_date", "") or ""),
            "source_hash": stable_hash(meeting),
            "mode": mode,
            "l2_events": meeting_events,
        }

    nodes = [_build_l2_node(label, linked) for label, linked in sorted(linked_by_label.items())]
    l2_view = {
        "schema_version": L2_VIEW_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "source": "share_mem",
        "share_mem_root": str(share_mem_root.resolve()),
        "source_tree_hash": source_tree_hash,
        "mode": mode,
        "l2_nodes": nodes,
    }
    unlinked_report = {
        "schema_version": L2_VIEW_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "source_tree_hash": source_tree_hash,
        "unlinked_count": len(unlinked_objects),
        "review_queue_count": len(review_queue),
        "unlinked_objects": unlinked_objects,
        "review_queue": review_queue,
    }
    manifest = {
        "schema_version": L2_VIEW_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "share_mem_root": str(share_mem_root.resolve()),
        "output_root": str(output_root.resolve()),
        "mode": mode,
        "source_tree_hash": source_tree_hash,
        "meeting_count": len(list(iter_meetings(tree))),
        "source_l1_count": source_l1_count,
        "linked_l1_count": len(l2_index),
        "unlinked_l1_count": len(unlinked_objects),
        "review_queue_count": len(review_queue),
        "l2_count": len(nodes),
        "l2_view_path": str((output_root / L2_VIEW_FILE_NAME).resolve()),
        "l2_index_path": str((output_root / L2_INDEX_FILE_NAME).resolve()),
        "unlinked_l1_report_path": str((output_root / L2_UNLINKED_FILE_NAME).resolve()),
    }
    return {
        "l2_view": l2_view,
        "l2_index": dict(sorted(l2_index.items())),
        "updates_by_meeting": updates_by_meeting,
        "unlinked_report": unlinked_report,
        "manifest": manifest,
    }


def build_l2_view_outputs(
    *,
    share_mem_root: Path | str = REPO_ROOT / "share_mem",
    output_root: Path | str = REPO_ROOT / "long_term" / "l2",
    mode: str = "hybrid",
    model: str | None = None,
    clean: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    del model  # Hybrid API assignment is intentionally not used in the first L2 builder.
    if mode not in SUPPORTED_L2_MODES:
        raise ValueError(f"Unsupported L2 mode: {mode}")
    share_root = Path(share_mem_root)
    out_root = Path(output_root)
    tree = load_share_mem_l1_tree(share_root)
    if clean and not dry_run:
        clean_l2_outputs(out_root)

    outputs = _build_outputs(
        tree=tree,
        share_mem_root=share_root,
        output_root=out_root,
        mode=mode,
    )
    if dry_run:
        return outputs["manifest"]

    _write_json(out_root / L2_VIEW_FILE_NAME, outputs["l2_view"])
    _write_json(out_root / L2_INDEX_FILE_NAME, outputs["l2_index"])
    _write_json(out_root / L2_UNLINKED_FILE_NAME, outputs["unlinked_report"])
    for meeting_id, update in sorted(outputs["updates_by_meeting"].items()):
        _write_json(out_root / L2_UPDATES_DIR_NAME / f"{meeting_id}.json", update)
    _write_json(out_root / L2_MANIFEST_FILE_NAME, outputs["manifest"])
    return outputs["manifest"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an L2 view from canonical share_mem L1 evidence."
    )
    parser.add_argument(
        "--share-mem-root",
        default=str(REPO_ROOT / "share_mem"),
        help="Root containing share_mem tree.json and meetings/.",
    )
    parser.add_argument(
        "--output-root",
        default=str(REPO_ROOT / "long_term" / "l2"),
        help="Output root for generated L2 view artifacts.",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(SUPPORTED_L2_MODES),
        default="hybrid",
        help="Assignment mode. The first implementation uses deterministic assignment for both modes.",
    )
    parser.add_argument("--model", default=None, help="Reserved for future Gemini-assisted assignment.")
    parser.add_argument("--clean", action="store_true", help="Clean generated L2 outputs.")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without writing.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    manifest = build_l2_view_outputs(
        share_mem_root=args.share_mem_root,
        output_root=args.output_root,
        mode=args.mode,
        model=args.model,
        clean=bool(args.clean),
        dry_run=bool(args.dry_run),
    )
    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    print(
        "[long_term] L2 view refreshed: "
        f"{manifest['l2_count']} L2 nodes, "
        f"{manifest['linked_l1_count']} linked L1, "
        f"{manifest['unlinked_l1_count']} unlinked L1"
    )
    print(f"L2 view: {manifest['l2_view_path']}")


if __name__ == "__main__":
    main()
