from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from .store import (
        DEFAULT_SHARE_MEM_ROOT,
        build_topic_view_manifest,
        iter_meetings,
        normalize_share_tree,
    )
except ImportError:  # pragma: no cover - direct script execution fallback
    from store import (  # type: ignore
        DEFAULT_SHARE_MEM_ROOT,
        build_topic_view_manifest,
        iter_meetings,
        normalize_share_tree,
    )

TOPIC_VIEW_SCHEMA_VERSION = 1
TOPIC_TREE_FILE_NAME = "topic_tree.json"
TOPIC_INDEX_FILE_NAME = "topic_index.json"
TOPIC_UPDATES_DIR_NAME = "topic_updates"
TOPIC_RESEARCH_LOGS_DIR_NAME = "topic_research_logs"
MEMORY_RELATIONS_INDEX_FILE_NAME = "memory_relations_index.json"
SUPPORTED_TOPIC_VIEW_MODES = {"hybrid"}
TopicAssignmentFn = Callable[..., dict[str, Any] | None]

TOPIC_ASSIGNMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["assign_existing", "new_l2", "new_l3"],
        },
        "root_topic_id": {"type": "string"},
        "topic_id": {"type": "string"},
        "root_label": {"type": "string"},
        "topic_label": {"type": "string"},
        "state_summary": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["action", "root_label", "topic_label", "state_summary"],
}

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
_SLUG_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)
_GENERIC_TOPICS = {
    "memory",
    "long-term",
    "long term",
    "short-term",
    "short term",
    "share_mem",
    "shared memory",
}
TYPE_LIKE_TOPIC_LABELS = {
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
OVER_BROAD_TOPIC_LABELS = {
    "memory architecture",
    "memory management",
}
PROTECTED_TOPIC_LABELS = {
    "data fragmentation",
    "memory processing architecture",
}
TOPIC_ALIAS_MAP = {
    "data-fragmentation": "data fragmentation",
    "data_fragmentation": "data fragmentation",
    "memory architecture": "memory architecture",
    "memory management": "memory management",
    "topic tree": "topic-tree",
    "topic_tree": "topic-tree",
}


class TopicViewHashMismatchError(RuntimeError):
    """Raised when an existing per-meeting topic update is stale."""


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _stable_hash(data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TopicApiCallLogger:
    def __init__(self, root: Path | str, run_id: str) -> None:
        safe_run_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(run_id or "topic_view")).strip("_")
        self.run_dir = Path(root) / TOPIC_RESEARCH_LOGS_DIR_NAME / safe_run_id
        self.api_calls_dir = self.run_dir / "api_calls"
        self.api_calls_dir.mkdir(parents=True, exist_ok=True)
        self._seq = 0

    def write_call(
        self,
        *,
        stage: str,
        attempt: int,
        model: str,
        config: dict[str, Any],
        schema: dict[str, Any],
        prompt: str,
        raw_response: str,
        parsed_json: dict[str, Any] | None,
        latency_sec: float,
        success: bool,
        error: dict[str, Any] | None,
    ) -> None:
        self._seq += 1
        safe_stage = re.sub(r"[^a-zA-Z0-9_.-]+", "_", stage).strip("_") or "topic_assignment"
        payload = {
            "seq": self._seq,
            "stage": stage,
            "attempt": attempt,
            "model": model,
            "config": config,
            "schema_hash": _stable_hash(schema),
            "schema": schema,
            "prompt": prompt,
            "raw_response": raw_response,
            "parsed_json": parsed_json,
            "latency_sec": round(float(latency_sec), 4),
            "success": success,
            "error": error,
            "logged_at_utc": utc_now_iso(),
        }
        call_path = self.api_calls_dir / f"{self._seq:03d}_{safe_stage}_attempt{attempt}.json"
        _write_json(call_path, payload)
        jsonl_path = self.api_calls_dir / "api_calls.jsonl"
        with jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def meeting_source_hash(meeting: dict[str, Any]) -> str:
    return _stable_hash(
        {
            "meeting_id": meeting.get("meeting_id", ""),
            "meeting_date": meeting.get("meeting_date", ""),
            "source_file": meeting.get("source_file", ""),
            "memory_objects": meeting.get("memory_objects", []),
        }
    )


def clean_topic_view_outputs(root: Path | str = DEFAULT_SHARE_MEM_ROOT) -> None:
    base = Path(root)
    for file_name in (TOPIC_TREE_FILE_NAME, TOPIC_INDEX_FILE_NAME):
        path = base / file_name
        if path.exists():
            path.unlink()
    for dir_name in (TOPIC_UPDATES_DIR_NAME, TOPIC_RESEARCH_LOGS_DIR_NAME):
        output_dir = base / dir_name
        if output_dir.exists():
            shutil.rmtree(output_dir)


def empty_topic_tree(*, source_tree_hash: str = "") -> dict[str, Any]:
    return {
        "schema_version": TOPIC_VIEW_SCHEMA_VERSION,
        "generated_at_utc": "",
        "source_tree_hash": source_tree_hash,
        "topic_roots": [],
    }


def load_topic_tree(root: Path | str = DEFAULT_SHARE_MEM_ROOT) -> dict[str, Any]:
    path = Path(root) / TOPIC_TREE_FILE_NAME
    if not path.exists():
        return empty_topic_tree()
    data = _load_json(path)
    if not isinstance(data, dict):
        raise RuntimeError(f"Topic tree must be a JSON object: {path}")
    return data


def load_topic_index(root: Path | str = DEFAULT_SHARE_MEM_ROOT) -> dict[str, Any]:
    path = Path(root) / TOPIC_INDEX_FILE_NAME
    if not path.exists():
        return {}
    data = _load_json(path)
    if not isinstance(data, dict):
        raise RuntimeError(f"Topic index must be a JSON object: {path}")
    return data


def topic_update_path(root: Path | str, meeting_id: str) -> Path:
    return Path(root) / TOPIC_UPDATES_DIR_NAME / f"{meeting_id}.json"


def iter_topic_update_files(root: Path | str) -> Iterable[Path]:
    updates_dir = Path(root) / TOPIC_UPDATES_DIR_NAME
    if not updates_dir.exists():
        return []
    return sorted(updates_dir.glob("*.json"), key=lambda path: path.name)


def load_relation_index(root: Path | str = DEFAULT_SHARE_MEM_ROOT) -> dict[str, Any]:
    path = Path(root) / MEMORY_RELATIONS_INDEX_FILE_NAME
    if not path.exists():
        return {}
    data = _load_json(path)
    if not isinstance(data, dict):
        raise RuntimeError(f"Memory relations index must be a JSON object: {path}")
    return data


def _topics(obj: dict[str, Any]) -> list[str]:
    raw_topics = obj.get("related_topics", [])
    if not isinstance(raw_topics, list):
        return []
    topics: list[str] = []
    for topic in raw_topics:
        clean = str(topic).strip().lower()
        if clean and clean not in topics:
            topics.append(clean)
    return topics


def _related_obj_ids(
    obj: dict[str, Any],
    relation_index: dict[str, Any] | None,
) -> list[str]:
    related: list[str] = []
    raw_related = obj.get("related_obj_ids", [])
    if isinstance(raw_related, list):
        related.extend(str(item).strip() for item in raw_related if str(item).strip())

    obj_id = str(obj.get("obj_id", "") or "").strip()
    raw_relations = relation_index.get(obj_id, []) if isinstance(relation_index, dict) else []
    if isinstance(raw_relations, list):
        for relation in raw_relations:
            if not isinstance(relation, dict):
                continue
            target_obj_id = str(relation.get("target_obj_id", "") or "").strip()
            if target_obj_id:
                related.append(target_obj_id)

    deduped: list[str] = []
    for obj_id in related:
        if obj_id not in deduped:
            deduped.append(obj_id)
    return deduped


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(str(text or ""))}


def normalize_topic_label(label: str) -> str:
    clean = re.sub(r"[_\s]+", " ", str(label or "").strip().lower())
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        return ""
    return TOPIC_ALIAS_MAP.get(clean, clean)


def _is_type_like_topic(label: str) -> bool:
    return normalize_topic_label(label) in TYPE_LIKE_TOPIC_LABELS


def _is_over_broad_topic(label: str) -> bool:
    return normalize_topic_label(label) in OVER_BROAD_TOPIC_LABELS


def _obj_text(obj: dict[str, Any]) -> str:
    topics = " ".join(_topics(obj))
    return " ".join(
        [
            str(obj.get("content", "") or ""),
            str(obj.get("evidence", "") or ""),
            topics,
        ]
    )


def _marker_in_text(text: str, marker: str) -> bool:
    clean = str(marker or "").lower().strip()
    if not clean:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9\-\s]*[a-z0-9]", clean):
        return re.search(rf"(?<![a-z0-9]){re.escape(clean)}(?![a-z0-9])", text) is not None
    return clean in text


def _has_any(text: str, markers: Iterable[str]) -> bool:
    return any(_marker_in_text(text, marker) for marker in markers)


def _concept_keys_for_obj(obj: dict[str, Any]) -> set[str]:
    text = _obj_text(obj).lower().replace("_", " ")
    topics = {normalize_topic_label(topic) for topic in _topics(obj)}
    concepts: set[str] = set()
    if _has_any(text, ("data fragmentation", "fragmentation", "chunk boundary", "chunk boundaries")):
        concepts.add("data fragmentation")
    if _has_any(text, ("segment repair", "repair mechanism", "crosses chunks", "cross chunk")):
        concepts.add("data fragmentation")
    if (
        "memory" in text
        and _has_any(
            text,
            (
                "hierarchical",
                "hierarchy",
                "top-down",
                "bottom-up",
                "processing architecture",
                "memory object",
                "memory objects",
                "objects and issues",
                "issues and objects",
                "issue node",
                "issue nodes",
                "issue represents",
                "parent object",
            ),
        )
        or ("l1" in text and ("l2" in text or "l3" in text))
    ):
        concepts.add("memory processing architecture")
    if _has_any(text, ("top-down", "bottom-up", "由上而下", "由下而上")) and _has_any(
        text,
        (
            "chunk",
            "chunks",
            "idea unit",
            "idea units",
            "segment",
            "segments",
            "text processing",
            "transcript processing",
            "merging",
        ),
    ):
        concepts.add("memory processing architecture")
    if _has_any(text, ("memo", "locomo", "multi-hop", "multi hop", "llm-as-judge")):
        concepts.add("memory evaluation strategy")
    if _has_any(text, ("topic-tree", "topic tree", "topic update", "append-only topic")):
        concepts.add("topic-tree")
    if _has_any(text, ("discard as l1", "importance score", "fade out", "fade-out", "inactive")):
        concepts.add("memory lifecycle")
    if _has_any(text, ("batch", "repaired segment", "complete segment")):
        concepts.add("batch definition")
    for topic in topics:
        if topic and topic not in _GENERIC_TOPICS and not _is_type_like_topic(topic):
            concepts.add(topic)
    return concepts


def _slug(label: str, *, fallback: str) -> str:
    clean = _SLUG_RE.sub("-", str(label or "").lower()).strip("-")
    return clean or fallback


def _root_label_for_obj(obj: dict[str, Any]) -> str:
    topics = _topics(obj)
    text = _obj_text(obj).lower()
    concepts = _concept_keys_for_obj(obj)
    if "data fragmentation" in concepts:
        return "data fragmentation"
    if "memory processing architecture" in concepts:
        return "memory"
    if (
        "memory" in text
        or "l1" in text
        or "long-term" in text
        or "short-term" in text
        or any(topic in {"topic-tree", "shared-l1", "share_mem"} for topic in topics)
    ):
        return "memory"
    if "poster" in text or "demo" in text or any("poster" in topic for topic in topics):
        return "poster-demo"
    if topics:
        for topic in topics:
            normalized = normalize_topic_label(topic)
            if normalized and not _is_type_like_topic(normalized):
                return normalized
    return "general"


def _topic_label_for_obj(obj: dict[str, Any], root_label: str) -> str:
    concepts = _concept_keys_for_obj(obj)
    for preferred in (
        "memory processing architecture",
        "data fragmentation",
        "topic-tree",
        "memory evaluation strategy",
        "memory lifecycle",
        "batch definition",
    ):
        if preferred in concepts:
            return preferred
    for topic in _topics(obj):
        normalized = normalize_topic_label(topic)
        if (
            normalized
            and normalized not in _GENERIC_TOPICS
            and normalized != root_label
            and not _is_type_like_topic(normalized)
            and not _is_over_broad_topic(normalized)
        ):
            return normalized
    return root_label


def _root_topic_id(root_label: str) -> str:
    return f"L3-{_slug(root_label, fallback='topic')}"


def _l2_topic_id(root_topic_id: str, topic_label: str) -> str:
    return f"L2-{root_topic_id[3:]}__{_slug(topic_label, fallback='topic')}"


def _find_root(topic_tree: dict[str, Any], root_topic_id: str) -> dict[str, Any] | None:
    for root in topic_tree.get("topic_roots", []):
        if isinstance(root, dict) and root.get("topic_id") == root_topic_id:
            return root
    return None


def _find_l2(root: dict[str, Any], topic_id: str) -> dict[str, Any] | None:
    for child in root.get("children", []):
        if isinstance(child, dict) and child.get("topic_id") == topic_id:
            return child
    return None


def _iter_l2_nodes(topic_tree: dict[str, Any]) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    for root in topic_tree.get("topic_roots", []):
        if not isinstance(root, dict):
            continue
        for child in root.get("children", []):
            if isinstance(child, dict):
                yield root, child


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _candidate_existing_topic(
    topic_tree: dict[str, Any],
    obj: dict[str, Any],
    relation_index: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], float] | None:
    obj_tokens = _tokens(_obj_text(obj))
    obj_topics = set(_topics(obj))
    obj_concepts = _concept_keys_for_obj(obj)
    related_obj_ids = set(_related_obj_ids(obj, relation_index))
    best: tuple[dict[str, Any], dict[str, Any], float] | None = None
    for root, child in _iter_l2_nodes(topic_tree):
        topic_payload = " ".join(
            [
                str(child.get("label", "") or ""),
                str(child.get("current_state", "") or ""),
                " ".join(str(item) for item in child.get("keywords", [])),
                " ".join(str(item) for item in child.get("object_ids", [])),
            ]
        )
        topic_tokens = _tokens(topic_payload)
        child_keywords = {normalize_topic_label(str(item)) for item in child.get("keywords", [])}
        child_concepts = {
            normalize_topic_label(str(child.get("label", "") or "")),
            *child_keywords,
        }
        keyword_overlap = len({normalize_topic_label(item) for item in obj_topics} & child_keywords)
        concept_overlap = len(obj_concepts & child_concepts)
        related_overlap = len(related_obj_ids & set(child.get("object_ids", [])))
        if _is_over_broad_topic(str(child.get("label", "") or "")) and not related_overlap and not concept_overlap:
            continue
        score = (
            _jaccard(obj_tokens, topic_tokens)
            + (0.25 * keyword_overlap)
            + (1.25 * concept_overlap)
            + (2.0 * related_overlap)
        )
        if score >= 0.45 and (best is None or score > best[2]):
            best = (root, child, score)
    return best


def _candidate_topic_summaries(
    topic_tree: dict[str, Any],
    obj: dict[str, Any],
    *,
    relation_index: dict[str, Any] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    obj_tokens = _tokens(_obj_text(obj))
    obj_topics = set(_topics(obj))
    obj_concepts = _concept_keys_for_obj(obj)
    related_obj_ids = set(_related_obj_ids(obj, relation_index))
    candidates: list[dict[str, Any]] = []
    for root, child in _iter_l2_nodes(topic_tree):
        topic_payload = " ".join(
            [
                str(child.get("label", "") or ""),
                str(child.get("current_state", "") or ""),
                " ".join(str(item) for item in child.get("keywords", [])),
            ]
        )
        topic_tokens = _tokens(topic_payload)
        child_keywords = {normalize_topic_label(str(item)) for item in child.get("keywords", [])}
        child_concepts = {
            normalize_topic_label(str(child.get("label", "") or "")),
            *child_keywords,
        }
        keyword_overlap = len({normalize_topic_label(item) for item in obj_topics} & child_keywords)
        concept_overlap = len(obj_concepts & child_concepts)
        matched_related_obj_ids = sorted(related_obj_ids & set(child.get("object_ids", [])))
        score = (
            _jaccard(obj_tokens, topic_tokens)
            + (0.25 * keyword_overlap)
            + (1.25 * concept_overlap)
            + (2.0 * len(matched_related_obj_ids))
        )
        candidates.append(
            {
                "root_topic_id": str(root.get("topic_id", "") or ""),
                "root_label": str(root.get("label", "") or ""),
                "topic_id": str(child.get("topic_id", "") or ""),
                "topic_label": str(child.get("label", "") or ""),
                "current_state": _short_text(str(child.get("current_state", "") or ""), 260),
                "recent_events": [
                    str(item)
                    for item in child.get("timeline_digest", [])[-3:]
                ],
                "keywords": [str(item) for item in child.get("keywords", [])],
                "concept_keys": sorted(child_concepts),
                "matched_related_obj_ids": matched_related_obj_ids,
                "score": round(score, 4),
            }
        )
    return sorted(candidates, key=lambda item: float(item["score"]), reverse=True)[:limit]


def _deterministic_assignment(
    topic_tree: dict[str, Any],
    obj: dict[str, Any],
    relation_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root_label = _root_label_for_obj(obj)
    topic_label = _topic_label_for_obj(obj, root_label)
    root_topic_id = _root_topic_id(root_label)
    topic_id = _l2_topic_id(root_topic_id, topic_label)
    existing_root = _find_root(topic_tree, root_topic_id)
    existing_child = _find_l2(existing_root, topic_id) if existing_root else None
    related_obj_ids = _related_obj_ids(obj, relation_index)
    if existing_child is not None:
        return {
            "action": "assign_existing",
            "root_topic_id": root_topic_id,
            "root_label": str(existing_root.get("label", root_label)) if existing_root else root_label,
            "topic_id": topic_id,
            "topic_label": str(existing_child["label"]),
            "previous_state": str(existing_child.get("current_state", "") or ""),
            "keywords": [str(keyword) for keyword in existing_child.get("keywords", [])],
            "assignment_method": "deterministic",
            "linked_prior_obj_ids": [
                obj_id
                for obj_id in related_obj_ids
                if obj_id in set(existing_child.get("object_ids", []))
            ],
        }
    candidate = _candidate_existing_topic(topic_tree, obj, relation_index=relation_index)
    if candidate is not None and set(related_obj_ids) & set(candidate[1].get("object_ids", [])):
        root, child, _score = candidate
        return {
            "action": "assign_existing",
            "root_topic_id": str(root["topic_id"]),
            "root_label": str(root["label"]),
            "topic_id": str(child["topic_id"]),
            "topic_label": str(child["label"]),
            "previous_state": str(child.get("current_state", "") or ""),
            "keywords": [str(keyword) for keyword in child.get("keywords", [])],
            "assignment_method": "deterministic",
            "linked_prior_obj_ids": sorted(set(related_obj_ids) & set(child.get("object_ids", []))),
        }
    if normalize_topic_label(topic_label) in PROTECTED_TOPIC_LABELS:
        if existing_root is not None:
            return _new_topic_assignment(
                action="new_l2",
                root_topic_id=root_topic_id,
                root_label=str(existing_root.get("label", root_label)),
                topic_id=topic_id,
                topic_label=topic_label,
                topics=_topics(obj),
                related_obj_ids=related_obj_ids,
            )
        return _new_topic_assignment(
            action="new_l3",
            root_topic_id=root_topic_id,
            root_label=root_label,
            topic_id=topic_id,
            topic_label=topic_label,
            topics=_topics(obj),
            related_obj_ids=related_obj_ids,
        )
    if existing_root is not None:
        return {
            "action": "new_l2",
            "root_topic_id": root_topic_id,
            "root_label": str(existing_root.get("label", root_label)),
            "topic_id": topic_id,
            "topic_label": topic_label,
            "previous_state": "",
            "keywords": sorted(set([root_label, topic_label, *_topics(obj)])),
            "assignment_method": "deterministic",
            "linked_prior_obj_ids": related_obj_ids,
        }

    candidate = _candidate_existing_topic(topic_tree, obj, relation_index=relation_index)
    if candidate is not None:
        root, child, _score = candidate
        return {
            "action": "assign_existing",
            "root_topic_id": str(root["topic_id"]),
            "root_label": str(root["label"]),
            "topic_id": str(child["topic_id"]),
            "topic_label": str(child["label"]),
            "previous_state": str(child.get("current_state", "") or ""),
            "keywords": [str(keyword) for keyword in child.get("keywords", [])],
            "assignment_method": "deterministic",
            "linked_prior_obj_ids": sorted(set(related_obj_ids) & set(child.get("object_ids", []))),
        }
    return {
        "action": "new_l3",
        "root_topic_id": root_topic_id,
        "root_label": root_label,
        "topic_id": topic_id,
        "topic_label": topic_label,
        "previous_state": "",
        "keywords": sorted(set([root_label, topic_label, *_topics(obj)])),
        "assignment_method": "deterministic",
        "linked_prior_obj_ids": related_obj_ids,
    }


def _should_keep_deterministic_assignment(
    deterministic: dict[str, Any],
    *,
    root_label: str,
    topic_label: str,
) -> bool:
    deterministic_root = normalize_topic_label(str(deterministic.get("root_label", "") or ""))
    deterministic_topic = normalize_topic_label(str(deterministic.get("topic_label", "") or ""))
    proposed_root = normalize_topic_label(root_label)
    proposed_topic = normalize_topic_label(topic_label)
    if _is_type_like_topic(proposed_root) or _is_type_like_topic(proposed_topic):
        return True
    if _is_over_broad_topic(proposed_topic):
        return True
    if deterministic_topic in PROTECTED_TOPIC_LABELS:
        return proposed_topic != deterministic_topic or proposed_root != deterministic_root
    return False


def _new_topic_assignment(
    *,
    action: str,
    root_topic_id: str,
    root_label: str,
    topic_id: str,
    topic_label: str,
    topics: list[str],
    related_obj_ids: list[str],
    assignment_method: str = "deterministic",
) -> dict[str, Any]:
    return {
        "action": action,
        "root_topic_id": root_topic_id,
        "root_label": root_label,
        "topic_id": topic_id,
        "topic_label": topic_label,
        "previous_state": "",
        "keywords": sorted(set([root_label, topic_label, *topics])),
        "assignment_method": assignment_method,
        "linked_prior_obj_ids": related_obj_ids,
    }


def _assignment_from_llm_decision(
    *,
    topic_tree: dict[str, Any],
    obj: dict[str, Any],
    deterministic: dict[str, Any],
    candidates: list[dict[str, Any]],
    decision: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(decision, dict):
        return deterministic
    action = str(decision.get("action", "") or "")
    if action not in {"assign_existing", "new_l2", "new_l3"}:
        return deterministic

    state_summary = _short_text(str(decision.get("state_summary", "") or ""), 520)
    rationale = _short_text(str(decision.get("rationale", "") or ""), 220)
    if action == "assign_existing":
        topic_id = str(decision.get("topic_id", "") or "")
        selected = next(
            (candidate for candidate in candidates if candidate.get("topic_id") == topic_id),
            None,
        )
        if selected is None:
            return deterministic
        root = _find_root(topic_tree, str(selected["root_topic_id"]))
        child = _find_l2(root, str(selected["topic_id"])) if root else None
        if child is None:
            return deterministic
        if _should_keep_deterministic_assignment(
            deterministic,
            root_label=str(selected["root_label"]),
            topic_label=str(selected["topic_label"]),
        ):
            return deterministic
        return {
            "action": action,
            "root_topic_id": str(selected["root_topic_id"]),
            "root_label": str(selected["root_label"]),
            "topic_id": str(selected["topic_id"]),
            "topic_label": str(selected["topic_label"]),
            "previous_state": str(child.get("current_state", "") or ""),
            "keywords": [str(keyword) for keyword in child.get("keywords", [])],
            "assignment_method": "llm",
            "llm_rationale": rationale,
            "state_summary": state_summary,
            "linked_prior_obj_ids": [
                str(item) for item in selected.get("matched_related_obj_ids", [])
            ],
        }

    if action == "new_l2":
        root_topic_id = str(decision.get("root_topic_id", "") or deterministic["root_topic_id"])
        root = _find_root(topic_tree, root_topic_id)
        if root is None:
            return deterministic
        root_label = str(root.get("label", "") or deterministic["root_label"])
        topic_label = str(decision.get("topic_label", "") or deterministic["topic_label"])
        if _should_keep_deterministic_assignment(
            deterministic,
            root_label=root_label,
            topic_label=topic_label,
        ):
            return deterministic
        topic_id = str(decision.get("topic_id", "") or "")
        if not topic_id:
            topic_id = _l2_topic_id(root_topic_id, topic_label)
        if _find_l2(root, topic_id) is not None:
            return deterministic
        return {
            "action": action,
            "root_topic_id": root_topic_id,
            "root_label": root_label,
            "topic_id": topic_id,
            "topic_label": topic_label,
            "previous_state": "",
            "keywords": sorted(set([root_label, topic_label, *_topics(obj)])),
            "assignment_method": "llm",
            "llm_rationale": rationale,
            "state_summary": state_summary,
            "linked_prior_obj_ids": [
                str(item) for item in deterministic.get("linked_prior_obj_ids", [])
            ],
        }

    root_label = str(decision.get("root_label", "") or deterministic["root_label"])
    topic_label = str(decision.get("topic_label", "") or deterministic["topic_label"])
    if _should_keep_deterministic_assignment(
        deterministic,
        root_label=root_label,
        topic_label=topic_label,
    ):
        return deterministic
    root_topic_id = str(decision.get("root_topic_id", "") or _root_topic_id(root_label))
    if _find_root(topic_tree, root_topic_id) is not None:
        return deterministic
    topic_id = str(decision.get("topic_id", "") or _l2_topic_id(root_topic_id, topic_label))
    return {
        "action": action,
        "root_topic_id": root_topic_id,
        "root_label": root_label,
        "topic_id": topic_id,
        "topic_label": topic_label,
        "previous_state": "",
        "keywords": sorted(set([root_label, topic_label, *_topics(obj)])),
        "assignment_method": "llm",
        "llm_rationale": rationale,
        "state_summary": state_summary,
        "linked_prior_obj_ids": [
            str(item) for item in deterministic.get("linked_prior_obj_ids", [])
        ],
    }


def _short_text(text: str, limit: int = 220) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def _state_after_event(previous_state: str, obj: dict[str, Any], meeting_id: str) -> str:
    event_text = _short_text(str(obj.get("content", "") or ""), 180)
    if not previous_state:
        return event_text
    combined = f"{previous_state} | {meeting_id}: {event_text}"
    return _short_text(combined, 520)


def _event_summary(obj: dict[str, Any]) -> str:
    return _short_text(str(obj.get("content", "") or ""), 180)


def _topic_assignment_prompt(
    *,
    meeting: dict[str, Any],
    obj: dict[str, Any],
    deterministic: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> str:
    payload = {
        "task": (
            "Assign one immutable L1 memory object to the append-only topic-tree "
            "view. Choose assign_existing only from topic_candidates. Choose new_l2 "
            "when the root topic exists but this L1 starts a distinct subtopic. "
            "Choose new_l3 when it starts a distinct major topic root. Do not rewrite "
            "old L1 evidence."
        ),
        "meeting": {
            "meeting_id": str(meeting.get("meeting_id", "") or ""),
            "meeting_date": str(meeting.get("meeting_date", "") or ""),
        },
        "new_l1": {
            "obj_id": str(obj.get("obj_id", "") or ""),
            "type": str(obj.get("type", "") or ""),
            "content": str(obj.get("content", "") or ""),
            "evidence": str(obj.get("evidence", "") or ""),
            "related_topics": _topics(obj),
            "related_obj_ids": _related_obj_ids(obj, None),
        },
        "deterministic_default": {
            key: deterministic.get(key)
            for key in (
                "action",
                "root_topic_id",
                "root_label",
                "topic_id",
                "topic_label",
            )
        },
        "topic_candidates": candidates,
        "output_contract": {
            "action": "assign_existing | new_l2 | new_l3",
            "topic_id": "required when action is assign_existing",
            "state_summary": "compact current state after applying this L1",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            return {}
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def create_gemini_topic_assigner(
    model: str,
    *,
    api_logger: TopicApiCallLogger | None = None,
) -> TopicAssignmentFn:
    model_name = str(model or "").strip()
    if not model_name:
        raise RuntimeError("Topic-tree LLM assignment requires a model name.")

    def _assign(**kwargs: Any) -> dict[str, Any] | None:
        try:
            from .l1.gemini_clients import create_gemini_client
        except ImportError:  # pragma: no cover - direct script execution fallback
            from l1.gemini_clients import create_gemini_client  # type: ignore

        prompt = _topic_assignment_prompt(
            meeting=kwargs["meeting"],
            obj=kwargs["obj"],
            deterministic=kwargs["deterministic"],
            candidates=kwargs["candidates"],
        )
        config = {
            "response_mime_type": "application/json",
            "response_json_schema": TOPIC_ASSIGNMENT_SCHEMA,
        }
        stage = f"topic_assignment:{str(kwargs['obj'].get('obj_id', '') or 'unknown')}"
        start = time.perf_counter()
        raw_response = ""
        parsed_json: dict[str, Any] | None = None
        client = create_gemini_client(None)
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            raw_response = response.text or ""
            parsed_json = _extract_json_object(raw_response)
            if api_logger is not None:
                api_logger.write_call(
                    stage=stage,
                    attempt=1,
                    model=model_name,
                    config=config,
                    schema=TOPIC_ASSIGNMENT_SCHEMA,
                    prompt=prompt,
                    raw_response=raw_response,
                    parsed_json=parsed_json,
                    latency_sec=time.perf_counter() - start,
                    success=True,
                    error=None,
                )
            return parsed_json
        except Exception as exc:
            if api_logger is not None:
                api_logger.write_call(
                    stage=stage,
                    attempt=1,
                    model=model_name,
                    config=config,
                    schema=TOPIC_ASSIGNMENT_SCHEMA,
                    prompt=prompt,
                    raw_response=raw_response,
                    parsed_json=parsed_json,
                    latency_sec=time.perf_counter() - start,
                    success=False,
                    error={"type": type(exc).__name__, "message": str(exc)},
                )
            raise

    return _assign


def _ensure_root(topic_tree: dict[str, Any], root_topic_id: str, root_label: str) -> dict[str, Any]:
    root = _find_root(topic_tree, root_topic_id)
    if root is not None:
        return root
    root = {
        "topic_id": root_topic_id,
        "level": "L3",
        "label": root_label,
        "keywords": [root_label],
        "current_state": "",
        "timeline_digest": [],
        "event_ids": [],
        "state_version_ids": [],
        "children": [],
    }
    topic_tree.setdefault("topic_roots", []).append(root)
    return root


def _ensure_l2(
    root: dict[str, Any],
    *,
    topic_id: str,
    topic_label: str,
    keywords: list[str],
) -> dict[str, Any]:
    child = _find_l2(root, topic_id)
    if child is not None:
        return child
    child = {
        "topic_id": topic_id,
        "parent_topic_id": root["topic_id"],
        "level": "L2",
        "label": topic_label,
        "keywords": keywords,
        "current_state": "",
        "timeline_digest": [],
        "event_ids": [],
        "state_version_ids": [],
        "object_ids": [],
    }
    root.setdefault("children", []).append(child)
    return child


def _apply_event_and_version(
    topic_tree: dict[str, Any],
    event: dict[str, Any],
    state_version: dict[str, Any],
) -> None:
    root = _ensure_root(
        topic_tree,
        str(event["root_topic_id"]),
        str(event["root_label"]),
    )
    child = _ensure_l2(
        root,
        topic_id=str(event["topic_id"]),
        topic_label=str(event["topic_label"]),
        keywords=[str(keyword) for keyword in event.get("keywords", [])],
    )
    event_id = str(event["event_id"])
    state_version_id = str(state_version["state_version_id"])
    obj_id = str(event["obj_id"])
    digest_entry = str(state_version.get("timeline_digest_entry", "") or "")

    if event_id not in child["event_ids"]:
        child["event_ids"].append(event_id)
    if state_version_id not in child["state_version_ids"]:
        child["state_version_ids"].append(state_version_id)
    if obj_id and obj_id not in child["object_ids"]:
        child["object_ids"].append(obj_id)
    if digest_entry:
        child["timeline_digest"].append(digest_entry)
    child["current_state"] = str(state_version.get("current_state", "") or "")

    if event_id not in root["event_ids"]:
        root["event_ids"].append(event_id)
    if state_version_id not in root["state_version_ids"]:
        root["state_version_ids"].append(state_version_id)
    if digest_entry:
        root["timeline_digest"].append(digest_entry)
    root["current_state"] = _short_text(
        " | ".join(
            str(item.get("current_state", "") or "")
            for item in root.get("children", [])
            if isinstance(item, dict) and item.get("current_state")
        ),
        520,
    )


def _sort_topic_tree(topic_tree: dict[str, Any]) -> dict[str, Any]:
    topic_tree["topic_roots"] = sorted(
        topic_tree.get("topic_roots", []),
        key=lambda root: str(root.get("topic_id", "")),
    )
    for root in topic_tree["topic_roots"]:
        root["children"] = sorted(
            root.get("children", []),
            key=lambda child: str(child.get("topic_id", "")),
        )
    return topic_tree


def _apply_topic_update(
    topic_tree: dict[str, Any],
    topic_index: dict[str, Any],
    data: dict[str, Any],
) -> None:
    versions = {
        str(item.get("state_version_id", "")): item
        for item in data.get("state_versions", [])
        if isinstance(item, dict)
    }
    for event in data.get("topic_events", []):
        if not isinstance(event, dict):
            continue
        state_version = versions.get(str(event.get("state_version_id", "")))
        if not isinstance(state_version, dict):
            continue
        _apply_event_and_version(topic_tree, event, state_version)
        obj_id = str(event.get("obj_id", "")).strip()
        if obj_id:
            topic_index[obj_id] = {
                "obj_id": obj_id,
                "meeting_id": str(event.get("meeting_id", "") or ""),
                "meeting_date": str(event.get("meeting_date", "") or ""),
                "root_topic_id": str(event.get("root_topic_id", "") or ""),
                "topic_id": str(event.get("topic_id", "") or ""),
                "event_id": str(event.get("event_id", "") or ""),
                "state_version_id": str(event.get("state_version_id", "") or ""),
                "topic_path": [
                    str(event.get("root_label", "") or ""),
                    str(event.get("topic_label", "") or ""),
                ],
                "action": str(event.get("action", "") or ""),
            }


def replay_topic_updates(
    root: Path | str = DEFAULT_SHARE_MEM_ROOT,
    *,
    source_tree_hash: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    topic_tree = empty_topic_tree(source_tree_hash=source_tree_hash)
    topic_index: dict[str, Any] = {}
    for update_path in iter_topic_update_files(root):
        data = _load_json(update_path)
        if not isinstance(data, dict):
            continue
        _apply_topic_update(topic_tree, topic_index, data)
    topic_tree["generated_at_utc"] = utc_now_iso()
    topic_tree["source_tree_hash"] = source_tree_hash
    return _sort_topic_tree(topic_tree), dict(sorted(topic_index.items()))


def _refresh_manifest_topic_view(root: Path) -> None:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, dict):
        return
    manifest["topic_view"] = build_topic_view_manifest(root)
    _write_json(manifest_path, manifest)


def _build_meeting_update(
    *,
    meeting: dict[str, Any],
    topic_tree: dict[str, Any],
    source_hash: str,
    mode: str,
    generated_at_utc: str,
    topic_assigner: TopicAssignmentFn | None,
    relation_index: dict[str, Any] | None,
) -> dict[str, Any]:
    meeting_id = str(meeting.get("meeting_id", "")).strip()
    meeting_date = str(meeting.get("meeting_date", "") or "")
    events: list[dict[str, Any]] = []
    versions: list[dict[str, Any]] = []

    for seq, obj in enumerate(meeting.get("memory_objects", []), start=1):
        if not isinstance(obj, dict):
            continue
        obj_id = str(obj.get("obj_id", "")).strip()
        if not obj_id:
            continue
        assignment = _deterministic_assignment(
            topic_tree,
            obj,
            relation_index=relation_index,
        )
        candidates = _candidate_topic_summaries(
            topic_tree,
            obj,
            relation_index=relation_index,
        )
        if topic_assigner is not None:
            decision = topic_assigner(
                meeting=meeting,
                obj=obj,
                deterministic=assignment,
                candidates=candidates,
            )
            assignment = _assignment_from_llm_decision(
                topic_tree=topic_tree,
                obj=obj,
                deterministic=assignment,
                candidates=candidates,
                decision=decision,
            )

        root_topic_id = str(assignment["root_topic_id"])
        root_label = str(assignment["root_label"])
        topic_id = str(assignment["topic_id"])
        topic_label = str(assignment["topic_label"])
        previous_state = str(assignment.get("previous_state", "") or "")
        action = str(assignment["action"])
        keywords = [str(keyword) for keyword in assignment.get("keywords", [])]

        event_id = f"TE-{meeting_id}-{seq:03d}"
        state_version_id = f"TS-{meeting_id}-{seq:03d}"
        current_state = str(assignment.get("state_summary", "") or "")
        if not current_state:
            current_state = _state_after_event(previous_state, obj, meeting_id)
        digest_entry = f"{meeting_id}: {_event_summary(obj)}"
        event = {
            "schema_version": TOPIC_VIEW_SCHEMA_VERSION,
            "event_id": event_id,
            "state_version_id": state_version_id,
            "obj_id": obj_id,
            "meeting_id": meeting_id,
            "meeting_date": meeting_date,
            "action": action,
            "root_topic_id": root_topic_id,
            "root_label": root_label,
            "topic_id": topic_id,
            "topic_label": topic_label,
            "topic_path": [root_label, topic_label],
            "keywords": keywords,
            "event_summary": _event_summary(obj),
            "object_type": str(obj.get("type", "") or ""),
            "importance": obj.get("importance", 0.0),
            "assignment_method": str(assignment.get("assignment_method", "deterministic")),
            "llm_rationale": str(assignment.get("llm_rationale", "") or ""),
            "linked_prior_obj_ids": [
                str(item) for item in assignment.get("linked_prior_obj_ids", [])
            ],
            "created_at_utc": generated_at_utc,
        }
        state_version = {
            "schema_version": TOPIC_VIEW_SCHEMA_VERSION,
            "state_version_id": state_version_id,
            "topic_id": topic_id,
            "root_topic_id": root_topic_id,
            "meeting_id": meeting_id,
            "meeting_date": meeting_date,
            "event_id": event_id,
            "source_obj_ids": [obj_id],
            "current_state": current_state,
            "timeline_digest_entry": digest_entry,
            "created_at_utc": generated_at_utc,
        }
        events.append(event)
        versions.append(state_version)
        _apply_event_and_version(topic_tree, event, state_version)

    return {
        "schema_version": TOPIC_VIEW_SCHEMA_VERSION,
        "meeting_id": meeting_id,
        "meeting_date": meeting_date,
        "source_hash": source_hash,
        "mode": mode,
        "generated_at_utc": generated_at_utc,
        "topic_events": events,
        "state_versions": versions,
    }


def _topic_counts(topic_tree: dict[str, Any]) -> tuple[int, int]:
    roots = [root for root in topic_tree.get("topic_roots", []) if isinstance(root, dict)]
    child_count = sum(
        len([child for child in root.get("children", []) if isinstance(child, dict)])
        for root in roots
    )
    event_count = sum(
        len(child.get("event_ids", []))
        for root in roots
        for child in root.get("children", [])
        if isinstance(child, dict)
    )
    return child_count, event_count


def build_topic_view_outputs(
    *,
    root: Path | str = DEFAULT_SHARE_MEM_ROOT,
    tree: dict[str, Any],
    mode: str = "hybrid",
    resume: bool = False,
    clean_topic_view: bool = False,
    force_meetings: set[str] | None = None,
    dry_run: bool = False,
    model: str | None = None,
    llm_assigner: TopicAssignmentFn | None = None,
    relation_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if mode not in SUPPORTED_TOPIC_VIEW_MODES:
        raise RuntimeError(f"Unsupported topic-tree mode: {mode}")
    base = Path(root)
    normalized_tree = normalize_share_tree(tree)
    source_tree_hash = _stable_hash(normalized_tree)
    meetings = list(iter_meetings(normalized_tree))
    force_ids = {str(item).strip() for item in (force_meetings or set()) if str(item).strip()}
    generated_at_utc = utc_now_iso()

    if dry_run:
        return {
            "schema_version": TOPIC_VIEW_SCHEMA_VERSION,
            "dry_run": True,
            "mode": mode,
            "meeting_count": len(meetings),
            "meeting_ids": [str(meeting.get("meeting_id", "") or "") for meeting in meetings],
            "would_write": [
                str(topic_update_path(base, str(meeting.get("meeting_id", "") or "")))
                for meeting in meetings
            ],
        }

    if clean_topic_view:
        clean_topic_view_outputs(base)

    topic_assigner = llm_assigner
    if topic_assigner is None and model:
        run_id = "topic_view_" + generated_at_utc.replace(":", "").replace("-", "").replace("Z", "")
        topic_assigner = create_gemini_topic_assigner(
            str(model),
            api_logger=TopicApiCallLogger(base, run_id),
        )
    active_relation_index = relation_index
    if active_relation_index is None:
        active_relation_index = load_relation_index(base)

    topic_tree = empty_topic_tree(source_tree_hash=source_tree_hash)
    working_topic_index: dict[str, Any] = {}
    processed_count = 0
    skipped_count = 0
    rebuild_from_here = clean_topic_view

    for meeting in meetings:
        meeting_id = str(meeting.get("meeting_id", "")).strip()
        if not meeting_id:
            continue
        source_hash = meeting_source_hash(meeting)
        update_path = topic_update_path(base, meeting_id)
        forced = meeting_id in force_ids
        if forced:
            rebuild_from_here = True

        if update_path.exists() and not rebuild_from_here:
            existing = _load_json(update_path)
            if not isinstance(existing, dict):
                raise RuntimeError(f"Topic update must be a JSON object: {update_path}")
            existing_hash = str(existing.get("source_hash", "") or "")
            if existing_hash != source_hash:
                raise TopicViewHashMismatchError(
                    f"Topic update source hash mismatch for {meeting_id}. "
                    "Use --force-meeting or --clean-topic-view to rebuild."
                )
            _apply_topic_update(topic_tree, working_topic_index, existing)
            skipped_count += 1
            continue

        if update_path.exists() and not forced and not clean_topic_view and rebuild_from_here:
            existing = _load_json(update_path)
            existing_hash = str(existing.get("source_hash", "") or "") if isinstance(existing, dict) else ""
            if existing_hash != source_hash:
                raise TopicViewHashMismatchError(
                    f"Topic update source hash mismatch for {meeting_id}. "
                    "Use --force-meeting or --clean-topic-view to rebuild."
                )

        update = _build_meeting_update(
            meeting=meeting,
            topic_tree=topic_tree,
            source_hash=source_hash,
            mode=mode,
            generated_at_utc=generated_at_utc,
            topic_assigner=topic_assigner,
            relation_index=active_relation_index,
        )
        _write_json(update_path, update)
        processed_count += 1

    topic_tree, topic_index = replay_topic_updates(base, source_tree_hash=source_tree_hash)
    _write_json(base / TOPIC_TREE_FILE_NAME, topic_tree)
    _write_json(base / TOPIC_INDEX_FILE_NAME, topic_index)
    _refresh_manifest_topic_view(base)
    topic_count, topic_event_count = _topic_counts(topic_tree)
    return {
        "schema_version": TOPIC_VIEW_SCHEMA_VERSION,
        "dry_run": False,
        "mode": mode,
        "generated_at_utc": generated_at_utc,
        "source_tree_hash": source_tree_hash,
        "meeting_count": len(meetings),
        "processed_meeting_count": processed_count,
        "skipped_meeting_count": skipped_count,
        "topic_count": topic_count,
        "topic_event_count": topic_event_count,
        "topic_tree_path": str((base / TOPIC_TREE_FILE_NAME).resolve()),
        "topic_index_path": str((base / TOPIC_INDEX_FILE_NAME).resolve()),
    }
