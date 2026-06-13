from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import load_json, utc_now_iso, write_json, write_text
from optimization.long_term_v2.effective_view import load_effective_topic_surface
from optimization.long_term_v2.profiles import (
    load_profile,
    profile_max_cjk_token_chars,
    profile_stopwords,
    profile_token_equivalents,
)
from optimization.long_term_v2.text_utils import jaccard, tokens
from share_mem.store import build_l1_index, load_share_tree


def _load_queries(path: Path | str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _rank_l1(query: str, l1_index: dict[str, dict[str, Any]], *, top_k: int, profile: dict[str, Any]) -> list[dict[str, Any]]:
    token_kwargs = {
        "stopwords": profile_stopwords(profile),
        "max_cjk_token_chars": profile_max_cjk_token_chars(profile),
    }
    expanded_query = _expand_equivalent_text(query, profile=profile)
    query_tokens = tokens(expanded_query, **token_kwargs)
    query_token_set = set(query_tokens)
    query_phrase = " ".join(query_tokens)
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for obj_id, row in l1_index.items():
        topics = [str(topic) for topic in row.get("topics", []) or []]
        text = " ".join(
            [
                str(row.get("content", "") or ""),
                str(row.get("evidence", "") or ""),
                " ".join(topics),
                str(row.get("type", "") or ""),
            ]
        )
        text_tokens = tokens(text, **token_kwargs)
        topic_tokens = tokens(" ".join(topics), **token_kwargs)
        score = max(
            jaccard(query_tokens, text_tokens),
            jaccard(query_tokens, topic_tokens) * 0.95,
        )
        phrase_bonus = 0.0
        for topic in topics:
            topic_tokens_for_phrase = tokens(topic, **token_kwargs)
            if not topic_tokens_for_phrase:
                continue
            topic_phrase = " ".join(topic_tokens_for_phrase)
            if topic_phrase and topic_phrase in query_phrase:
                phrase_bonus += 0.14
            elif set(topic_tokens_for_phrase).issubset(query_token_set):
                phrase_bonus += 0.08
        try:
            importance = float(row.get("importance", 0.0) or 0.0)
        except (TypeError, ValueError):
            importance = 0.0
        score += min(0.35, phrase_bonus) + importance * 0.015
        if score <= 0:
            continue
        scored.append((score, obj_id, row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {
            "obj_id": obj_id,
            "score": round(score, 4),
            "meeting_id": row.get("meeting_id", ""),
            "type": row.get("type", ""),
            "content": row.get("content", "")[:260],
        }
        for score, obj_id, row in scored[:top_k]
    ]


def _semantic_topic_hit(
    expected_l2_ids: set[str],
    selected_l2_labels: set[str],
    profile: dict[str, Any] | None = None,
) -> bool:
    profile = profile or {}
    if not expected_l2_ids:
        return bool(selected_l2_labels)
    expected_token_sets = []
    for expected_id in expected_l2_ids:
        expected_text = _expand_equivalent_text(str(expected_id).replace("L2-", "").replace("-", " "), profile=profile)
        expected_tokens = set(tokens(expected_text))
        if expected_tokens:
            expected_token_sets.append(expected_tokens)
    if not expected_token_sets:
        return False
    for label in selected_l2_labels:
        label_tokens = set(tokens(_expand_equivalent_text(label.replace("L2-", "").replace("-", " "), profile=profile)))
        for expected_tokens in expected_token_sets:
            overlap = expected_tokens & label_tokens
            if len(overlap) >= 2 or (overlap and len(expected_tokens) <= 2):
                return True
    return False


def _semantic_label_hit(
    *,
    expected_labels: set[str],
    selected_labels: set[str],
    profile: dict[str, Any] | None = None,
) -> bool:
    profile = profile or {}
    if not expected_labels:
        return bool(selected_labels)
    expected_token_sets = [
        set(tokens(_expand_equivalent_text(label, profile=profile)))
        for label in expected_labels
        if str(label).strip()
    ]
    for selected in selected_labels:
        selected_tokens = set(tokens(_expand_equivalent_text(selected, profile=profile)))
        for expected_tokens in expected_token_sets:
            if not expected_tokens:
                continue
            overlap = expected_tokens & selected_tokens
            if len(overlap) >= 2 or (overlap and len(expected_tokens) <= 2):
                return True
    return False


def _expand_equivalent_text(text: str, *, profile: dict[str, Any]) -> str:
    expanded = [text]
    equivalents = profile_token_equivalents(profile)
    for raw in tokens(text):
        equivalent = equivalents.get(raw)
        if equivalent:
            expanded.append(equivalent)
    return " ".join(expanded)


def evaluate_retrieval(
    *,
    run_root: Path | str,
    queries_path: Path | str,
    share_mem_root: Path | str = "share_mem",
    top_k_l1: int = 60,
    out_subdir: str = "retrieval_eval",
) -> dict[str, Any]:
    root = Path(run_root)
    queries = _load_queries(queries_path)
    l1_index = build_l1_index(load_share_tree(share_mem_root))
    manifest = load_json(root / "manifest.json") if (root / "manifest.json").exists() else {}
    profile: dict[str, Any] = {}
    profile_path = manifest.get("profile_path")
    if profile_path and Path(str(profile_path)).exists():
        profile = load_profile(str(profile_path))
    effective_surface = load_effective_topic_surface(root)
    l2_index = effective_surface["l2_index"]
    l3_index = effective_surface["l3_index"]
    results: list[dict[str, Any]] = []
    recall_values: list[float] = []
    l2_hits = 0
    semantic_l2_hits = 0
    l3_hits = 0
    semantic_l3_hits = 0
    for idx, query_row in enumerate(queries, start=1):
        query = str(query_row.get("query", "") or "")
        selected_l1 = _rank_l1(query, l1_index, top_k=top_k_l1, profile=profile)
        selected_ids = {row["obj_id"] for row in selected_l1}
        expected = set(query_row.get("expected_obj_ids", []) or [])
        expected_l2 = set(query_row.get("expected_l2_ids", []) or [])
        expected_l2_labels = set(query_row.get("expected_l2_labels", []) or [])
        expected_l3 = set(query_row.get("expected_l3_ids", []) or [])
        expected_l3_labels = set(query_row.get("expected_l3_labels", []) or [])
        obj_recall = len(expected & selected_ids) / max(len(expected), 1) if expected else 0.0
        selected_l2 = {
            str(l2_index[obj_id].get("l2_id", ""))
            for obj_id in selected_ids
            if obj_id in l2_index and isinstance(l2_index[obj_id], dict)
        }
        selected_l2_labels = {
            str(l2_index[obj_id].get("l2_label", ""))
            for obj_id in selected_ids
            if obj_id in l2_index and isinstance(l2_index[obj_id], dict)
        }
        selected_l3 = {
            str(l3_index[obj_id].get("parent_l3_id", ""))
            for obj_id in selected_ids
            if obj_id in l3_index and isinstance(l3_index[obj_id], dict)
        }
        selected_l3_labels = {
            str(l3_index[obj_id].get("parent_l3_label", ""))
            for obj_id in selected_ids
            if obj_id in l3_index and isinstance(l3_index[obj_id], dict)
        }
        suppressed_l2_index = effective_surface.get("suppressed_l2_index", {}) or {}
        selected_suppressed_l1_ids = sorted(selected_ids & set(suppressed_l2_index))
        selected_suppressed_l2_ids = sorted(
            {
                str(suppressed_l2_index[obj_id].get("l2_id", ""))
                for obj_id in selected_suppressed_l1_ids
                if isinstance(suppressed_l2_index.get(obj_id), dict)
                and str(suppressed_l2_index[obj_id].get("l2_id", ""))
            }
        )
        l2_hit = bool(expected_l2 & selected_l2) if expected_l2 else bool(selected_l2)
        semantic_l2_hit = (
            _semantic_label_hit(
                expected_labels=expected_l2_labels,
                selected_labels=selected_l2_labels,
                profile=profile,
            )
            if expected_l2_labels
            else _semantic_topic_hit(expected_l2, selected_l2_labels, profile=profile)
        )
        l3_hit = bool(expected_l3 & selected_l3) if expected_l3 else bool(selected_l3)
        semantic_l3_hit = _semantic_label_hit(
            expected_labels=expected_l3_labels,
            selected_labels=selected_l3_labels,
            profile=profile,
        )
        recall_values.append(obj_recall)
        l2_hits += int(l2_hit)
        semantic_l2_hits += int(semantic_l2_hit)
        l3_hits += int(l3_hit)
        semantic_l3_hits += int(semantic_l3_hit)
        results.append(
            {
                "query_id": f"q{idx:03d}",
                "query": query,
                "expected_obj_ids": sorted(expected),
                "matched_expected_obj_ids": sorted(expected & selected_ids),
                "expected_l2_ids": sorted(expected_l2),
                "expected_l2_labels": sorted(expected_l2_labels),
                "expected_l3_ids": sorted(expected_l3),
                "expected_l3_labels": sorted(expected_l3_labels),
                "selected_l1": selected_l1,
                "selected_l2_ids": sorted(selected_l2),
                "selected_l2_labels": sorted(selected_l2_labels),
                "selected_l3_ids": sorted(selected_l3),
                "selected_l3_labels": sorted(selected_l3_labels),
                "suppressed_l2_ids_available": effective_surface["suppressed_l2_ids"],
                "suppressed_selected_l1_count": len(selected_suppressed_l1_ids),
                "selected_suppressed_l1_ids": selected_suppressed_l1_ids,
                "selected_suppressed_l2_ids": selected_suppressed_l2_ids,
                "expected_obj_recall_at_context": round(obj_recall, 4),
                "expected_l2_hit": l2_hit,
                "expected_l2_semantic_hit": semantic_l2_hit,
                "expected_l3_hit": l3_hit,
                "expected_l3_semantic_hit": semantic_l3_hit,
            }
        )
    summary = {
        "query_count": len(queries),
        "avg_expected_obj_recall_at_context": round(sum(recall_values) / max(len(recall_values), 1), 4),
        "expected_l2_hit_rate": round(l2_hits / max(len(queries), 1), 4),
        "expected_l2_semantic_hit_rate": round(semantic_l2_hits / max(len(queries), 1), 4),
        "expected_l3_hit_rate": round(l3_hits / max(len(queries), 1), 4),
        "expected_l3_semantic_hit_rate": round(semantic_l3_hits / max(len(queries), 1), 4),
        "top_k_l1": top_k_l1,
    }
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "queries_path": str(Path(queries_path).resolve()),
        "effective_topic_surface": {
            "has_topic_review": effective_surface["has_topic_review"],
            "has_corpus_theme_l3": effective_surface.get("has_corpus_theme_l3", False),
            "has_l3_child_review": effective_surface.get("has_l3_child_review", False),
            "l3_surface_source": effective_surface.get("l3_surface_source", "raw_l3"),
            "active_l2_count": effective_surface["active_l2_count"],
            "suppressed_l2_count": effective_surface["suppressed_l2_count"],
            "suppressed_l2_index_count": effective_surface["suppressed_l2_index_count"],
        },
        "summary": summary,
        "queries": results,
    }
    out = root / out_subdir
    write_json(out / "retrieval_eval_report.json", report)
    write_text(
        out / "retrieval_eval_report.md",
        "\n".join(
            [
                "# Optimization v2 Retrieval Eval",
                "",
                f"- queries: {summary['query_count']}",
                f"- avg expected L1 recall: {summary['avg_expected_obj_recall_at_context']}",
                f"- expected L2 hit rate: {summary['expected_l2_hit_rate']}",
                f"- expected L2 semantic hit rate: {summary['expected_l2_semantic_hit_rate']}",
                f"- expected L3 hit rate: {summary['expected_l3_hit_rate']}",
                f"- expected L3 semantic hit rate: {summary['expected_l3_semantic_hit_rate']}",
                "",
            ]
        ),
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate optimization v2 lexical retrieval against query gold ids.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--share-mem-root", default="share_mem")
    parser.add_argument("--top-k-l1", type=int, default=60)
    parser.add_argument("--out-subdir", default="retrieval_eval")
    args = parser.parse_args()
    report = evaluate_retrieval(
        run_root=args.run_root,
        queries_path=args.queries,
        share_mem_root=args.share_mem_root,
        top_k_l1=args.top_k_l1,
        out_subdir=args.out_subdir,
    )
    print(
        "[optimization:v2] retrieval eval complete: "
        f"avg_l1_recall={report['summary']['avg_expected_obj_recall_at_context']}"
    )


if __name__ == "__main__":
    main()
