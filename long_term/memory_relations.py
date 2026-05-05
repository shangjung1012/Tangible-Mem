"""Cross-meeting relation sidecar helpers for L1 memory objects."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from io_utils import save_json
from l1_quality import l1_quality_hashes

RELATIONS_INDEX_SCHEMA_VERSION = 1
RELATION_TYPES = {
    "continues",
    "resolves",
    "supersedes",
    "contradicts",
    "reactivates",
    "supports",
    "repeats",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
_RESOLVE_CUES = ("resolved", "solved", "completed", "fixed", "done", "解決", "完成", "已處理")
_SUPERSEDE_CUES = ("replace", "instead", "supersede", "abandon", "改成", "改用", "取代", "棄用")
_CONTRADICT_CUES = ("contradict", "conflict", "wrong", "failed", "no longer", "衝突", "失敗", "不成立")
MIN_RELATION_CANDIDATE_SIMILARITY = 0.16
MIN_RELATION_CANDIDATE_TOPIC_OVERLAP = 0.25
MAX_TARGET_CANDIDATES_PER_SOURCE = 16

_CONCEPT_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("dynamic_tool_calling_read", ("function calling", "tool calling", "工具調用", "函式呼叫"), ("read", "line", "chunk", "逐字稿", "讀取", "行數")),
    ("read_write_memory_update", ("read", "`read`", "write", "`write`"), ("memory database", "memory db", "記憶資料庫")),
    ("idea_unit_grouping", ("idea unit", "idea units", "想法單元"), ("same topic", "continuation", "完整", "連續", "延續", "分割", "合併")),
    ("rag_baseline_comparison", ("rag",), ("compare", "comparison", "baseline", "evaluation", "demo", "比較", "評估", "展示")),
    ("memory_object_schema", ("memory object", "memory objects", "記憶物件"), ("type", "content", "evidence", "related topics", "欄位", "證據")),
    ("l123_hierarchy", ("l1", "l2", "l3"), ("hierarchy", "tree", "summary", "層級", "樹", "摘要")),
    ("memory_separation", ("short-term", "long-term", "短期", "長期"), ("separate", "separation", "distinguish", "區分", "分開")),
    ("forgetting_mechanism", ("forgetting", "forgotten", "forget", "fade", "decay", "遺忘", "衰減"), ("relevancy", "relevance", "importance", "decay", "衰減", "重要性", "相關性")),
    ("demo_dataset_strategy", ("dataset", "資料集", "simulate", "生成", "模擬"), ("demo", "demonstration", "展示", "示範", "演示")),
)

_VIEWPOINT_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("compare_unit_generation_baselines", ("fixed-size", "fixed size", "sentence-by-sentence", "逐句", "固定大小"), ("baseline", "baselines", "compare", "comparison", "評估", "比較")),
    ("compare_memory_architecture_with_rag", ("rag",), ("compare", "comparison", "contrast", "baseline", "比較", "展示", "demo")),
    ("short_long_memory_storage_distinction", ("short-term", "long-term", "短期", "長期"), ("separate", "separation", "differentiate", "distinguish", "儲存", "詳細", "精簡")),
    ("long_term_forgetting_decay", ("forgetting", "forgotten", "forget", "fade", "fade out", "decay", "遺忘", "忘記", "衰減"), ("relevancy", "relevance", "importance", "threshold", "weight", "重要性", "相關性", "權重", "衰減")),
    ("demo_own_meeting_dataset", ("own meeting", "meeting transcripts", "primary dataset", "我們自己的dataset", "自己的會議", "會議資料集"), ("demo", "demonstration", "evaluate", "evaluation", "展示", "示範", "評估")),
    ("idea_unit_cross_span_merging", ("idea unit", "idea units", "想法單元"), ("pack", "merge", "higher-level", "overlap", "打包", "合併", "重疊")),
    ("idea_unit_demo_scope", ("idea unit", "idea units", "想法單元"), ("demo", "demonstration", "exhibition", "五月", "專題展", "展示")),
    ("memory_object_schema_fields", ("memory object", "memory objects", "記憶物件"), ("type", "content", "evidence", "related topics", "欄位", "證據")),
)


def memory_relations_default_path(tree_path: Path) -> Path:
    return tree_path.parent / "memory_relations_index.json"


def load_memory_relations_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid memory relations index JSON: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Memory relations index must be a JSON object: {path}")
    return data


def save_memory_relations_index(path: Path, index: dict[str, Any]) -> None:
    save_json(path, index)


def merge_memory_relations_index(
    path: Path,
    updates: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    existing = load_memory_relations_index(path)
    if updates:
        existing.update(updates)
        save_memory_relations_index(path, existing)
    return existing


def remove_memory_relations_for_meeting(path: Path, meeting_id: str) -> dict[str, Any]:
    existing = load_memory_relations_index(path)
    if not existing:
        return existing
    filtered: dict[str, Any] = {}
    changed = False
    for source_obj_id, relations in existing.items():
        if not isinstance(relations, list):
            changed = True
            continue
        kept = [
            relation
            for relation in relations
            if not (
                isinstance(relation, dict)
                and (
                    str(relation.get("source_meeting_id", "")).strip() == meeting_id
                    or str(relation.get("target_meeting_id", "")).strip() == meeting_id
                )
            )
        ]
        if kept:
            filtered[str(source_obj_id)] = kept
        changed = changed or len(kept) != len(relations)
    if changed:
        save_memory_relations_index(path, filtered)
    return filtered


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(str(text or ""))}


def _jaccard(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _topics(obj: dict[str, Any]) -> set[str]:
    raw_topics = obj.get("related_topics", [])
    if not isinstance(raw_topics, list):
        return set()
    return {str(topic).strip().lower() for topic in raw_topics if str(topic).strip()}


def _text(obj: dict[str, Any]) -> str:
    return " ".join(
        [
            str(obj.get("type", "") or ""),
            str(obj.get("content", "") or ""),
            str(obj.get("evidence", "") or ""),
            " ".join(sorted(_topics(obj))),
        ]
    ).strip()


def _contains_any(text: str, cues: tuple[str, ...]) -> bool:
    lower = str(text or "").lower()
    return any(cue.lower() in lower for cue in cues)


def _keys_from_rules(
    text: str,
    rules: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...],
) -> set[str]:
    lowered = str(text or "").lower()
    keys: set[str] = set()
    for key, required_left, required_right in rules:
        if _contains_any(lowered, required_left) and _contains_any(lowered, required_right):
            keys.add(key)
    return keys


def concept_keys_for_obj(obj: dict[str, Any]) -> set[str]:
    """Coarse identity keys shared by cross-meeting relation matching."""
    return _keys_from_rules(_text(obj), _CONCEPT_RULES)


def viewpoint_keys_for_obj(obj: dict[str, Any]) -> set[str]:
    """Stricter identity keys for deciding whether an old viewpoint returned."""
    return _keys_from_rules(_text(obj), _VIEWPOINT_RULES)


def relation_hashes(
    *,
    source_obj: dict[str, Any],
    target_obj: dict[str, Any],
) -> dict[str, str]:
    source_hashes = l1_quality_hashes(source_obj)
    target_hashes = l1_quality_hashes(target_obj)
    return {
        "source_content_hash": source_hashes["content_hash"],
        "source_evidence_hash": source_hashes["evidence_hash"],
        "target_content_hash": target_hashes["content_hash"],
        "target_evidence_hash": target_hashes["evidence_hash"],
    }


def relation_is_current(
    relation: dict[str, Any],
    *,
    source_obj: dict[str, Any] | None = None,
    target_obj: dict[str, Any] | None = None,
) -> bool:
    """Return False when relation metadata belongs to stale source/target content."""
    if source_obj is not None:
        has_source_hashes = (
            "source_content_hash" in relation or "source_evidence_hash" in relation
        )
        if has_source_hashes:
            source_hashes = l1_quality_hashes(source_obj)
            if (
                relation.get("source_content_hash") != source_hashes["content_hash"]
                or relation.get("source_evidence_hash") != source_hashes["evidence_hash"]
            ):
                return False
    if target_obj is not None:
        has_target_hashes = (
            "target_content_hash" in relation or "target_evidence_hash" in relation
        )
        if has_target_hashes:
            target_hashes = l1_quality_hashes(target_obj)
            if (
                relation.get("target_content_hash") != target_hashes["content_hash"]
                or relation.get("target_evidence_hash") != target_hashes["evidence_hash"]
            ):
                return False
    return True


def _quality_is_usable(obj: dict[str, Any], quality_index: dict[str, Any] | None) -> bool:
    obj_id = str(obj.get("obj_id", "")).strip()
    meta = (quality_index or {}).get(obj_id)
    if not isinstance(meta, dict):
        return True
    expected = l1_quality_hashes(obj)
    stale = (
        meta.get("content_hash") != expected["content_hash"]
        or meta.get("evidence_hash") != expected["evidence_hash"]
    )
    if stale:
        return True
    return str(meta.get("quality_level", "")).strip().lower() != "weak"


def _relation_for_pair(
    source: dict[str, Any],
    target: dict[str, Any],
    *,
    similarity: float,
    topic_overlap: float,
    shared_concept_keys: set[str],
    shared_viewpoint_keys: set[str],
) -> tuple[str, float] | None:
    source_type = str(source.get("type", "") or "").lower()
    target_type = str(target.get("type", "") or "").lower()
    source_text = _text(source)
    key_bonus = 0.18 if shared_viewpoint_keys else 0.10 if shared_concept_keys else 0.0
    confidence = round(
        min(0.95, 0.48 * similarity + 0.32 * topic_overlap + key_bonus + 0.18),
        3,
    )

    if target_type in {"todo", "open_question"} and source_type in {"decision", "method_change", "result"}:
        if (similarity >= 0.18 or shared_viewpoint_keys or shared_concept_keys) and _contains_any(source_text, _RESOLVE_CUES):
            return "resolves", max(confidence, 0.72)
    if target_type in {"decision", "method_change"} and source_type in {"decision", "method_change"}:
        if (similarity >= 0.18 or shared_viewpoint_keys or shared_concept_keys) and _contains_any(source_text, _SUPERSEDE_CUES):
            return "supersedes", max(confidence, 0.74)
    if target_type in {"result", "argument", "decision", "method_change"}:
        if (similarity >= 0.18 or shared_viewpoint_keys or shared_concept_keys) and _contains_any(source_text, _CONTRADICT_CUES):
            return "contradicts", max(confidence, 0.72)
    if source_type == "argument" and target_type in {"decision", "method_change"}:
        if similarity >= 0.16 or topic_overlap >= 0.25 or shared_concept_keys:
            return "supports", max(confidence, 0.62)
    if source_type == target_type and (
        similarity >= 0.34 or topic_overlap >= 0.55 or shared_viewpoint_keys
    ):
        return "repeats", max(confidence, 0.68)
    if shared_viewpoint_keys:
        return "reactivates", max(confidence, 0.70)
    if target_type in {"todo", "open_question", "result", "argument"} and (
        similarity >= 0.24 or topic_overlap >= 0.40 or shared_concept_keys
    ):
        return "reactivates", max(confidence, 0.64)
    if similarity >= 0.20 or topic_overlap >= 0.34 or shared_concept_keys:
        return "continues", max(confidence, 0.58)
    return None


def _is_relation_candidate(
    *,
    similarity: float,
    topic_overlap: float,
    shared_concept_keys: set[str],
    shared_viewpoint_keys: set[str],
) -> bool:
    return (
        bool(shared_viewpoint_keys)
        or bool(shared_concept_keys)
        or topic_overlap >= MIN_RELATION_CANDIDATE_TOPIC_OVERLAP
        or similarity >= MIN_RELATION_CANDIDATE_SIMILARITY
    )


def _iter_meeting_objects(tree: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for meeting in tree.get("meetings", []):
        meeting_id = str(meeting.get("meeting_id", "")).strip()
        for obj in meeting.get("memory_objects", []):
            if isinstance(obj, dict):
                rows.append({"meeting_id": meeting_id, "obj": obj})
    return rows


def build_cross_meeting_relations(
    *,
    tree: dict[str, Any],
    source_meeting: dict[str, Any],
    quality_index: dict[str, Any] | None = None,
    max_targets_per_obj: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    source_meeting_id = str(source_meeting.get("meeting_id", "")).strip()
    old_rows = [
        row
        for row in _iter_meeting_objects(tree)
        if row["meeting_id"] and row["meeting_id"] != source_meeting_id
    ]
    updates: dict[str, list[dict[str, Any]]] = {}
    for source in source_meeting.get("memory_objects", []):
        if not isinstance(source, dict):
            continue
        source_obj_id = str(source.get("obj_id", "")).strip()
        if not source_obj_id:
            continue
        source_topics = _topics(source)
        source_concept_keys = concept_keys_for_obj(source)
        source_viewpoint_keys = viewpoint_keys_for_obj(source)
        relations: list[dict[str, Any]] = []
        target_candidates: list[dict[str, Any]] = []
        for row in old_rows:
            target = row["obj"]
            target_obj_id = str(target.get("obj_id", "")).strip()
            if not target_obj_id or not _quality_is_usable(target, quality_index):
                continue
            target_topics = _topics(target)
            topic_overlap = (
                len(source_topics & target_topics) / len(source_topics | target_topics)
                if source_topics and target_topics
                else 0.0
            )
            similarity = _jaccard(_text(source), _text(target))
            target_concept_keys = concept_keys_for_obj(target)
            target_viewpoint_keys = viewpoint_keys_for_obj(target)
            shared_concept_keys = source_concept_keys & target_concept_keys
            shared_viewpoint_keys = source_viewpoint_keys & target_viewpoint_keys
            if not _is_relation_candidate(
                similarity=similarity,
                topic_overlap=topic_overlap,
                shared_concept_keys=shared_concept_keys,
                shared_viewpoint_keys=shared_viewpoint_keys,
            ):
                continue
            target_candidates.append(
                {
                    "row": row,
                    "target": target,
                    "similarity": similarity,
                    "topic_overlap": topic_overlap,
                    "shared_concept_keys": shared_concept_keys,
                    "shared_viewpoint_keys": shared_viewpoint_keys,
                    "candidate_rank": (
                        len(shared_viewpoint_keys),
                        len(shared_concept_keys),
                        topic_overlap,
                        similarity,
                    ),
                }
            )
        target_candidates.sort(
            key=lambda item: (
                -item["candidate_rank"][0],
                -item["candidate_rank"][1],
                -item["candidate_rank"][2],
                -item["candidate_rank"][3],
                str(item["target"].get("obj_id", "")),
            )
        )
        for candidate in target_candidates[:MAX_TARGET_CANDIDATES_PER_SOURCE]:
            row = candidate["row"]
            target = candidate["target"]
            target_obj_id = str(target.get("obj_id", "")).strip()
            similarity = float(candidate["similarity"])
            topic_overlap = float(candidate["topic_overlap"])
            shared_concept_keys = set(candidate["shared_concept_keys"])
            shared_viewpoint_keys = set(candidate["shared_viewpoint_keys"])
            relation = _relation_for_pair(
                source,
                target,
                similarity=similarity,
                topic_overlap=topic_overlap,
                shared_concept_keys=shared_concept_keys,
                shared_viewpoint_keys=shared_viewpoint_keys,
            )
            if relation is None:
                continue
            relation_type, confidence = relation
            relations.append(
                {
                    "schema_version": RELATIONS_INDEX_SCHEMA_VERSION,
                    "target_obj_id": target_obj_id,
                    "relation": relation_type,
                    "confidence": round(float(confidence), 3),
                    "reason": (
                        f"similarity={similarity:.3f}; topic_overlap={topic_overlap:.3f}; "
                        f"shared_viewpoints={','.join(sorted(shared_viewpoint_keys)) or 'none'}; "
                        f"shared_concepts={','.join(sorted(shared_concept_keys)) or 'none'}"
                    ),
                    "shared_viewpoint_keys": sorted(shared_viewpoint_keys),
                    "shared_concept_keys": sorted(shared_concept_keys),
                    "source_meeting_id": source_meeting_id,
                    "target_meeting_id": row["meeting_id"],
                    **relation_hashes(source_obj=source, target_obj=target),
                }
            )
        relations.sort(
            key=lambda item: (
                -float(item.get("confidence", 0.0)),
                str(item.get("relation", "")),
                str(item.get("target_obj_id", "")),
            )
        )
        if relations:
            updates[source_obj_id] = relations[: max(1, int(max_targets_per_obj))]
    return updates


def format_memory_relations_tag(
    obj: dict[str, Any],
    relations_index: dict[str, Any] | None,
) -> str:
    obj_id = str(obj.get("obj_id", "")).strip()
    relations = (relations_index or {}).get(obj_id, [])
    if not isinstance(relations, list) or not relations:
        return "relations=none"
    parts: list[str] = []
    for relation in relations[:3]:
        if not isinstance(relation, dict):
            continue
        if not relation_is_current(relation, source_obj=obj):
            continue
        rel_type = str(relation.get("relation", "")).strip()
        target = str(relation.get("target_obj_id", "")).strip()
        if rel_type and target:
            parts.append(f"{rel_type}:{target}")
    return "relations=" + (",".join(parts) if parts else "none")
