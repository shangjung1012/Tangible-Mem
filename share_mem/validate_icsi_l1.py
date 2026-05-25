from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SETUP_KEYWORDS = {
    "af",
    "audio",
    "breath noise",
    "channel",
    "counter",
    "equipment",
    "gain",
    "microphone",
    "mic",
    "recording",
    "seating",
    "setup",
    "wireless",
}

DURABLE_SETUP_KEYWORDS = {
    "annotation",
    "asr",
    "corpus",
    "data quality",
    "data collection",
    "far-field",
    "frame-synchronous",
    "frame-synchronously",
    "meeting recorder",
    "metadata",
    "methodology",
    "natural meeting",
    "near-field",
    "policy",
    "project scope",
    "project vision",
    "privacy",
    "procedure",
    "quality issue",
    "recording procedure",
    "recording rule",
    "reusable",
    "speech recognition",
    "transcription",
    "video recording",
}

SOURCE_DATA_ONLY_KEYWORDS = {
    "audio setup mapping",
    "assigned channel",
    "channel number",
    "channel mapping",
    "device placement",
    "dummy pda",
    "headset announcement",
    "low gain",
    "meeting kickoff",
    "meeting metadata",
    "meeting number",
    "microphone inventory",
    "microphone type",
    "participant list",
    "participant names",
    "pzm",
    "recorded on",
    "speaker introduction",
    "stationary microphone",
}

SOURCE_DATA_DURABLE_KEYWORDS = {
    "annotation",
    "asr",
    "corpus metadata policy",
    "data collection",
    "data quality risk",
    "downstream indexing",
    "far-field",
    "frame-synchronous",
    "frame-synchronously",
    "instruction",
    "methodology",
    "near-field",
    "policy",
    "rationale",
    "recording rule",
    "reusable",
    "speech recognition",
    "speaker identification",
}

TOPIC_ALIAS_GROUPS: dict[str, set[str]] = {
    "annotation data model": {
        "annotation format",
        "annotation linking",
        "data format",
        "data model",
        "data representation",
        "data schema",
        "database format",
        "event linkage",
        "id-based linking",
        "stable ids",
        "temporal annotation",
        "temporal annotation schema",
        "timeline representation",
        "xml",
        "xml format",
        "xml schema",
    },
    "recording data quality": {
        "af indicator",
        "audio quality",
        "breath noise",
        "data quality",
        "microphone technique",
        "noise artifact",
        "recording issues",
        "recording procedure",
    },
}

DUPLICATE_AUTO_MERGE_MIN_CONTENT_SIMILARITY = 0.35


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _tokens(value: Any) -> set[str]:
    return set(re.findall(r"[a-z0-9_'-]+", _normalize_text(value)))


def _jaccard(left: Any, right: Any) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _has_cjk(value: Any) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(value or "")))


def _obj_text(obj: dict[str, Any]) -> str:
    topics = " ".join(str(topic) for topic in obj.get("related_topics", []))
    return " ".join(
        [
            str(obj.get("content", "")),
            str(obj.get("evidence", "")),
            topics,
        ]
    )


def _is_setup_like(obj: dict[str, Any]) -> bool:
    text = _normalize_text(_obj_text(obj))
    return any(keyword in text for keyword in SETUP_KEYWORDS)


def _has_durable_setup_signal(obj: dict[str, Any]) -> bool:
    text = _normalize_text(_obj_text(obj))
    return any(keyword in text for keyword in DURABLE_SETUP_KEYWORDS)


def _is_source_data_only(obj: dict[str, Any]) -> bool:
    text = _normalize_text(_obj_text(obj))
    if not any(keyword in text for keyword in SOURCE_DATA_ONLY_KEYWORDS):
        return False
    return not any(keyword in text for keyword in SOURCE_DATA_DURABLE_KEYWORDS)


def _clean_topic(topic: Any) -> str:
    return _normalize_text(topic).replace("_", " ")


def _topic_alias_clusters(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    topic_counts: Counter[str] = Counter()
    for obj in objects:
        topic_counts.update(_clean_topic(topic) for topic in obj.get("related_topics", []))

    clusters: list[dict[str, Any]] = []
    for canonical, aliases in TOPIC_ALIAS_GROUPS.items():
        observed = {
            alias: topic_counts[alias]
            for alias in sorted(aliases)
            if topic_counts.get(alias, 0) > 0
        }
        if len(observed) < 2:
            continue
        clusters.append(
            {
                "canonical_topic": canonical,
                "observed_alias_count": len(observed),
                "observed_object_mentions": sum(observed.values()),
                "aliases": observed,
            }
        )
    return clusters


def _same_evidence_duplicate_groups(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in objects:
        normalized_evidence = _normalize_text(obj.get("evidence", ""))
        if not normalized_evidence:
            continue
        buckets[normalized_evidence].append(obj)

    groups: list[dict[str, Any]] = []
    for evidence, rows in buckets.items():
        if len(rows) < 2:
            continue
        content_similarity_values: list[float] = []
        for i, left in enumerate(rows):
            for right in rows[i + 1 :]:
                content_similarity_values.append(_jaccard(left.get("content", ""), right.get("content", "")))
        avg_similarity = (
            sum(content_similarity_values) / len(content_similarity_values)
            if content_similarity_values
            else 0.0
        )
        groups.append(
            {
                "evidence_preview": evidence[:240],
                "obj_ids": [str(row.get("obj_id", "")) for row in rows],
                "types": sorted({str(row.get("type", "")) for row in rows}),
                "avg_content_similarity": round(avg_similarity, 3),
                "reason_codes": ["same_evidence"],
            }
        )
    return groups


def _content_similarity_to_keep(keep: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, float]:
    keep_id = str(keep.get("obj_id", ""))
    return {
        str(row.get("obj_id", "")): round(_jaccard(keep.get("content", ""), row.get("content", "")), 3)
        for row in rows
        if str(row.get("obj_id", "")) and str(row.get("obj_id", "")) != keep_id
    }


def _score_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "avg": None}
    return {
        "count": len(values),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "avg": round(sum(values) / len(values), 3),
    }


def build_icsi_l1_quality_report(objects: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [dict(obj) for obj in objects]
    setup_noise: list[dict[str, Any]] = []
    high_importance_setup: list[dict[str, Any]] = []
    content_language_violations: list[dict[str, Any]] = []

    for obj in rows:
        importance = float(obj.get("importance") or 0.0)
        if _is_setup_like(obj) and not _has_durable_setup_signal(obj):
            issue = {
                "obj_id": obj.get("obj_id", ""),
                "meeting_id": obj.get("meeting_id", ""),
                "type": obj.get("type", ""),
                "importance": round(importance, 3),
                "content_preview": str(obj.get("content", ""))[:240],
                "reason_codes": ["setup_like_without_durable_signal"],
            }
            setup_noise.append(issue)
            if importance > 0.55:
                high_importance_setup.append(
                    {
                        **issue,
                        "reason_codes": issue["reason_codes"] + ["importance_above_setup_review_cap"],
                    }
                )
        if _has_cjk(obj.get("content", "")):
            content_language_violations.append(
                {
                    "obj_id": obj.get("obj_id", ""),
                    "meeting_id": obj.get("meeting_id", ""),
                    "content_preview": str(obj.get("content", ""))[:240],
                    "reason_codes": ["content_contains_cjk"],
                }
            )

    duplicate_groups = _same_evidence_duplicate_groups(rows)
    topic_alias_clusters = _topic_alias_clusters(rows)
    importances = [float(obj.get("importance") or 0.0) for obj in rows]

    return {
        "schema_version": 1,
        "generated_at_utc": _utc_now_iso(),
        "summary": {
            "object_count": len(rows),
            "setup_noise_count": len(setup_noise),
            "high_importance_setup_count": len(high_importance_setup),
            "same_evidence_duplicate_group_count": len(duplicate_groups),
            "topic_alias_cluster_count": len(topic_alias_clusters),
            "content_language_violation_count": len(content_language_violations),
            "importance": _score_summary(importances),
        },
        "setup_noise_objects": setup_noise,
        "high_importance_setup_objects": high_importance_setup,
        "same_evidence_duplicate_groups": duplicate_groups,
        "topic_alias_clusters": topic_alias_clusters,
        "content_language_violations": content_language_violations,
        "notes": [
            "This validator is review-only. It never mutates raw L1 objects.",
            "It intentionally does not auto-reclassify decision objects based on words like proposed, suggested, or considered.",
        ],
    }


def _object_brief(obj: dict[str, Any], reason_codes: list[str], action: str) -> dict[str, Any]:
    return {
        "obj_id": obj.get("obj_id", ""),
        "meeting_id": obj.get("meeting_id", ""),
        "type": obj.get("type", ""),
        "canonical_importance": round(float(obj.get("importance") or 0.0), 3),
        "action": action,
        "reason_codes": reason_codes,
        "content_preview": str(obj.get("content", ""))[:240],
        "evidence_preview": _normalize_text(obj.get("evidence", ""))[:240],
    }


def _choose_duplicate_representative(rows: list[dict[str, Any]]) -> dict[str, Any]:
    type_priority = {
        "decision": 7,
        "approach_change": 6,
        "open_issue": 5,
        "action_item": 4,
        "finding": 3,
        "proposal": 2,
        "argument": 1,
    }
    return max(
        rows,
        key=lambda row: (
            float(row.get("importance") or 0.0),
            type_priority.get(str(row.get("type", "")), 0),
            len(str(row.get("content", ""))),
        ),
    )


def build_icsi_l1_review_gate(objects: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Build a sidecar-only ICSI review/drop gate.

    The gate recommends review actions and a filtered candidate view. It never
    mutates raw L1 objects and never reclassifies decisions from surface words.
    """
    rows = [dict(obj) for obj in objects]
    by_obj_id = {str(obj.get("obj_id", "")): obj for obj in rows}
    quality_report = build_icsi_l1_quality_report(rows)

    drop_candidates: dict[str, dict[str, Any]] = {}
    review_candidates: dict[str, dict[str, Any]] = {}
    review_items: list[dict[str, Any]] = []

    for item in quality_report.get("setup_noise_objects", []):
        obj_id = str(item.get("obj_id", ""))
        obj = by_obj_id.get(obj_id)
        if not obj:
            continue
        reason_codes = list(item.get("reason_codes", []))
        if item.get("importance", 0) > 0.55:
            reason_codes.append("importance_above_setup_review_cap")
        review_candidates[obj_id] = _object_brief(
            obj,
            sorted(set(reason_codes + ["needs_human_review"])),
            "review_candidate",
        )

    for obj in rows:
        obj_id = str(obj.get("obj_id", ""))
        if not obj_id or obj_id in drop_candidates:
            continue
        if _is_source_data_only(obj):
            drop_candidates[obj_id] = _object_brief(
                obj,
                ["source_data_only", "not_durable_l1"],
                "drop_candidate",
            )
            review_candidates.pop(obj_id, None)

    duplicate_reviews: list[dict[str, Any]] = []
    merge_candidate_obj_ids: set[str] = set()
    duplicate_review_candidate_obj_ids: set[str] = set()
    for index, group in enumerate(_same_evidence_duplicate_groups(rows), start=1):
        group_rows = [by_obj_id[obj_id] for obj_id in group["obj_ids"] if obj_id in by_obj_id]
        if len(group_rows) < 2:
            continue
        keep_pool = [
            row
            for row in group_rows
            if str(row.get("obj_id", "")) not in drop_candidates
        ]
        keep = _choose_duplicate_representative(keep_pool or group_rows)
        keep_id = str(keep.get("obj_id", ""))
        similarity_to_keep = _content_similarity_to_keep(keep, group_rows)
        merge_ids = [
            str(row.get("obj_id", ""))
            for row in group_rows
            if str(row.get("obj_id", "")) != keep_id
            and similarity_to_keep.get(str(row.get("obj_id", "")), 0.0)
            >= DUPLICATE_AUTO_MERGE_MIN_CONTENT_SIMILARITY
        ]
        manual_review_ids = [
            str(row.get("obj_id", ""))
            for row in group_rows
            if str(row.get("obj_id", "")) != keep_id
            and str(row.get("obj_id", "")) not in merge_ids
        ]
        merge_candidate_obj_ids.update(merge_ids)
        duplicate_review_candidate_obj_ids.update(manual_review_ids)
        duplicate_reviews.append(
            {
                "group_id": f"same-evidence-{index:03d}",
                "action": "merge_review",
                "reason_codes": ["same_evidence_duplicate"],
                "obj_ids": [str(row.get("obj_id", "")) for row in group_rows],
                "types": sorted({str(row.get("type", "")) for row in group_rows}),
                "recommended_keep_obj_id": keep_id,
                "merge_candidate_obj_ids": merge_ids,
                "manual_review_obj_ids": manual_review_ids,
                "content_similarity_to_keep": similarity_to_keep,
                "avg_content_similarity": group.get("avg_content_similarity", 0.0),
                "note": (
                    "Review-only recommendation. Low-similarity same-evidence "
                    "objects stay in the filtered view for manual review; no "
                    "object type is rewritten."
                ),
            }
        )

    for item in drop_candidates.values():
        review_items.append(item)
    for item in review_candidates.values():
        review_items.append(item)
    for duplicate in duplicate_reviews:
        for obj_id in duplicate["merge_candidate_obj_ids"]:
            obj = by_obj_id.get(obj_id)
            if obj and obj_id not in drop_candidates:
                review_items.append(
                    _object_brief(
                        obj,
                        ["same_evidence_duplicate", "merge_candidate"],
                        "merge_candidate",
                    )
                )
        for obj_id in duplicate["manual_review_obj_ids"]:
            obj = by_obj_id.get(obj_id)
            if obj and obj_id not in drop_candidates:
                review_items.append(
                    _object_brief(
                        obj,
                        ["same_evidence_duplicate", "needs_manual_duplicate_review"],
                        "duplicate_review_candidate",
                    )
                )

    dropped_ids = set(drop_candidates)
    filtered_ids = [
        str(obj.get("obj_id", ""))
        for obj in rows
        if str(obj.get("obj_id", "")) not in dropped_ids
        and str(obj.get("obj_id", "")) not in merge_candidate_obj_ids
    ]

    return {
        "schema_version": 1,
        "generated_at_utc": _utc_now_iso(),
        "scope": "icsi_l1_review_drop_gate",
        "mode": "sidecar_only",
        "summary": {
            "object_count": len(rows),
            "review_item_count": len(review_items),
            "drop_candidate_count": len(dropped_ids),
            "review_candidate_count": len(review_candidates),
            "merge_review_group_count": len(duplicate_reviews),
            "merge_candidate_count": len(merge_candidate_obj_ids),
            "duplicate_review_candidate_count": len(duplicate_review_candidate_obj_ids),
            "filtered_candidate_count": len(filtered_ids),
        },
        "drop_candidate_obj_ids": sorted(dropped_ids),
        "merge_candidate_obj_ids": sorted(merge_candidate_obj_ids),
        "duplicate_review_candidate_obj_ids": sorted(duplicate_review_candidate_obj_ids),
        "filtered_candidate_obj_ids": filtered_ids,
        "review_items": review_items,
        "duplicate_reviews": duplicate_reviews,
        "topic_normalization_reviews": quality_report.get("topic_alias_clusters", []),
        "notes": [
            "This gate is sidecar-only. It does not modify share_mem/tree.json or meeting files.",
            "Filtered candidate ids are for ICSI experiment review only.",
            "It intentionally does not auto-reclassify decision objects based on words like proposed, suggested, or considered.",
            "Grace default runs do not call this ICSI-only gate.",
        ],
    }


def build_icsi_filtered_view(
    objects: Iterable[dict[str, Any]],
    gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [dict(obj) for obj in objects]
    gate = gate or build_icsi_l1_review_gate(rows)
    allowed = set(gate.get("filtered_candidate_obj_ids", []))
    return {
        "schema_version": 1,
        "generated_at_utc": _utc_now_iso(),
        "source": "icsi_l1_review_gate",
        "sidecar_only": True,
        "object_count": len(allowed),
        "memory_objects": [obj for obj in rows if str(obj.get("obj_id", "")) in allowed],
    }


def _load_objects_from_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("meetings"), list):
        objects: list[dict[str, Any]] = []
        for meeting in data.get("meetings", []):
            meeting_id = str(meeting.get("meeting_id", ""))
            for obj in meeting.get("memory_objects", []):
                row = dict(obj)
                row.setdefault("meeting_id", meeting_id)
                objects.append(row)
        return objects
    if isinstance(data, dict) and isinstance(data.get("memory_objects"), list):
        meeting_id = str(data.get("meeting_id", ""))
        return [{**dict(obj), "meeting_id": obj.get("meeting_id", meeting_id)} for obj in data["memory_objects"]]
    if isinstance(data, list):
        return [dict(obj) for obj in data]
    raise ValueError(f"Unsupported ICSI L1 JSON shape: {path}")


def load_icsi_l1_objects(root: Path | str) -> list[dict[str, Any]]:
    path = Path(root)
    if path.is_file():
        return _load_objects_from_json(path)
    tree_path = path / "tree.json"
    if tree_path.exists():
        return _load_objects_from_json(tree_path)
    meetings_dir = path / "meetings"
    if meetings_dir.exists():
        objects: list[dict[str, Any]] = []
        for meeting_path in sorted(meetings_dir.glob("*.json")):
            objects.extend(_load_objects_from_json(meeting_path))
        return objects
    raise FileNotFoundError(f"No tree.json or meetings/*.json found under {path}")


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# ICSI L1 Quality Report",
        "",
        "This report is review-only and does not modify raw L1 evidence.",
        "",
        "## Summary",
        "",
        f"- object_count: {summary.get('object_count', 0)}",
        f"- setup_noise_count: {summary.get('setup_noise_count', 0)}",
        f"- high_importance_setup_count: {summary.get('high_importance_setup_count', 0)}",
        f"- same_evidence_duplicate_group_count: {summary.get('same_evidence_duplicate_group_count', 0)}",
        f"- topic_alias_cluster_count: {summary.get('topic_alias_cluster_count', 0)}",
        f"- content_language_violation_count: {summary.get('content_language_violation_count', 0)}",
        "",
        "## Top Review Items",
        "",
    ]
    for key, title in [
        ("high_importance_setup_objects", "High-Importance Setup Objects"),
        ("same_evidence_duplicate_groups", "Same-Evidence Duplicate Groups"),
        ("topic_alias_clusters", "Topic Alias Clusters"),
        ("content_language_violations", "Content Language Violations"),
    ]:
        lines.extend([f"### {title}", ""])
        items = report.get(key, [])
        if not items:
            lines.extend(["- none", ""])
            continue
        for item in items[:10]:
            if key == "same_evidence_duplicate_groups":
                lines.append(
                    f"- {', '.join(item.get('obj_ids', []))}: "
                    f"types={', '.join(item.get('types', []))}; "
                    f"avg_content_similarity={item.get('avg_content_similarity')}"
                )
            elif key == "topic_alias_clusters":
                lines.append(
                    f"- {item.get('canonical_topic')}: "
                    f"{item.get('observed_alias_count')} aliases, "
                    f"{item.get('observed_object_mentions')} mentions"
                )
            else:
                lines.append(
                    f"- {item.get('obj_id', '')}: importance={item.get('importance', '')} "
                    f"{item.get('content_preview', '')}"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _markdown_gate(gate: dict[str, Any]) -> str:
    summary = gate.get("summary", {})
    lines = [
        "# ICSI L1 Review Gate",
        "",
        "This is a sidecar-only review/drop gate. It does not modify raw L1 evidence.",
        "",
        "## Summary",
        "",
        f"- object_count: {summary.get('object_count', 0)}",
        f"- review_item_count: {summary.get('review_item_count', 0)}",
        f"- drop_candidate_count: {summary.get('drop_candidate_count', 0)}",
        f"- review_candidate_count: {summary.get('review_candidate_count', 0)}",
        f"- merge_review_group_count: {summary.get('merge_review_group_count', 0)}",
        f"- merge_candidate_count: {summary.get('merge_candidate_count', 0)}",
        f"- duplicate_review_candidate_count: {summary.get('duplicate_review_candidate_count', 0)}",
        f"- filtered_candidate_count: {summary.get('filtered_candidate_count', 0)}",
        "",
        "## Drop / Merge Review Items",
        "",
    ]
    review_items = gate.get("review_items", [])
    if not review_items:
        lines.extend(["- none", ""])
    else:
        for item in review_items[:20]:
            lines.append(
                f"- {item.get('obj_id')}: action={item.get('action')} "
                f"importance={item.get('canonical_importance')} "
                f"reasons={', '.join(item.get('reason_codes', []))} "
                f"{item.get('content_preview', '')}"
            )
        lines.append("")

    lines.extend(["## Duplicate Reviews", ""])
    duplicates = gate.get("duplicate_reviews", [])
    if not duplicates:
        lines.extend(["- none", ""])
    else:
        for item in duplicates[:20]:
            lines.append(
                f"- {item.get('group_id')}: keep={item.get('recommended_keep_obj_id')} "
                f"merge={', '.join(item.get('merge_candidate_obj_ids', [])) or 'none'} "
                f"review={', '.join(item.get('manual_review_obj_ids', [])) or 'none'}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_icsi_l1_quality_report(
    objects: Iterable[dict[str, Any]],
    out_dir: Path | str,
) -> dict[str, Any]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    report = build_icsi_l1_quality_report(objects)
    (out_path / "icsi_l1_quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_path / "icsi_l1_quality_report.md").write_text(
        _markdown_report(report),
        encoding="utf-8",
    )
    return report


def write_icsi_l1_review_gate(
    objects: Iterable[dict[str, Any]],
    out_dir: Path | str,
) -> dict[str, Any]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    rows = [dict(obj) for obj in objects]
    gate = build_icsi_l1_review_gate(rows)
    filtered = build_icsi_filtered_view(rows, gate)
    (out_path / "icsi_l1_review_gate.json").write_text(
        json.dumps(gate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_path / "icsi_l1_review_gate.md").write_text(
        _markdown_gate(gate),
        encoding="utf-8",
    )
    (out_path / "icsi_l1_filtered_view.json").write_text(
        json.dumps(filtered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return gate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate ICSI share_mem-style L1 output quality.")
    parser.add_argument("--root", required=True, help="ICSI share_mem-style root, tree.json, or meeting JSON.")
    parser.add_argument("--out", required=True, help="Output directory for JSON/Markdown reports.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    objects = load_icsi_l1_objects(Path(args.root))
    report = write_icsi_l1_quality_report(objects, Path(args.out))
    gate = write_icsi_l1_review_gate(objects, Path(args.out))
    summary = report["summary"]
    gate_summary = gate["summary"]
    print(
        "[share_mem] ICSI L1 quality report: "
        f"{summary['object_count']} objects, "
        f"{summary['setup_noise_count']} setup-noise review items, "
        f"{summary['same_evidence_duplicate_group_count']} duplicate groups; "
        f"review gate drops {gate_summary['drop_candidate_count']} and filters to "
        f"{gate_summary['filtered_candidate_count']} candidates"
    )


if __name__ == "__main__":
    main()
