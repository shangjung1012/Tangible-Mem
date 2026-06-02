from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, utc_now_iso, write_json
from optimization.long_term_v2.profiles import load_profile, profile_facet_names, profile_facet_seed_terms
from optimization.long_term_v2.profiles import (
    profile_generic_topic_labels,
    profile_generic_ngram_terms,
    profile_max_cjk_token_chars,
    profile_rejected_topic_labels,
    profile_role_artifact_tokens,
    profile_role_artifact_terms,
    profile_stopwords,
    profile_type_like_labels,
)
from optimization.long_term_v2.schemas import SEMANTIC_KEY_SCHEMA_VERSION
from optimization.long_term_v2.text_utils import ngrams, token_sequences
from share_mem.store import iter_l1_objects, load_share_tree


def _object_text(obj: dict[str, Any]) -> str:
    return " ".join(
        [
            str(obj.get("content", "") or ""),
            str(obj.get("evidence", "") or ""),
        ]
    )


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _has_ascii_token(text: str) -> bool:
    return any(re.fullmatch(r"[a-z0-9]+", part) for part in text.split())


def _is_role_list_artifact(term: str, *, profile: dict[str, Any]) -> bool:
    parts = term.split()
    role_terms = profile_role_artifact_terms(profile)
    role_tokens = profile_role_artifact_tokens(profile)
    role_count = sum(1 for part in parts if part in role_tokens)
    if term in role_terms or role_count >= 2:
        return True
    return False


def _candidate_ngrams(text: str, *, profile: dict[str, Any]) -> list[str]:
    sequences = token_sequences(
        text,
        stopwords=profile_stopwords(profile),
        max_cjk_token_chars=profile_max_cjk_token_chars(profile),
    )
    terms = []
    for token_list in sequences:
        for term in ngrams(token_list, min_n=1, max_n=3, generic_terms=profile_generic_ngram_terms(profile)):
            if _is_role_list_artifact(term, profile=profile):
                continue
            terms.append(term)
    return terms


def _top_terms(text: str, *, profile: dict[str, Any], max_terms: int = 8) -> list[str]:
    candidates = _candidate_ngrams(text, profile=profile)
    if str(profile.get("topic_key_language", "") or "").lower().startswith("en"):
        english_candidates = [term for term in candidates if _has_ascii_token(term) and not _has_cjk(term)]
        if english_candidates:
            candidates = english_candidates
    counts = Counter(candidates)
    generic_labels = profile_generic_topic_labels(profile)
    rejected_labels = profile_rejected_topic_labels(profile)
    type_like_labels = profile_type_like_labels(profile)

    def score_term(term: str, count: int) -> tuple[float, int, str]:
        clean = " ".join(term.split())
        if clean in rejected_labels or clean in type_like_labels:
            return (999.0, 0, term)
        parts = term.split()
        if clean.startswith("term ") or clean.startswith("memory long"):
            return (999.0, 0, term)
        if len(parts) == 1 and parts[0] in generic_labels:
            return (999.0, 0, term)
        generic_count = sum(1 for part in parts if part in generic_labels)
        specific_count = len(parts) - generic_count
        phrase_bonus = 1.6 if len(parts) >= 3 else 1.15 if len(parts) == 2 else 0.0
        score = min(count, 4) * 2.5 + phrase_bonus + min(specific_count, 3) * 0.25
        if len(parts) == 1:
            score -= 0.9
        if len(parts) == 1 and generic_count:
            score -= 2.5
        if len(parts) >= 2 and specific_count == 0:
            score -= 0.4
        score -= generic_count * 0.15
        return (-score, -len(parts), term)

    ranked = sorted(
        counts.items(),
        key=lambda item: score_term(item[0], item[1]),
    )
    selected: list[str] = []
    for term, _ in ranked:
        clean = " ".join(term.split())
        if clean in rejected_labels or clean in type_like_labels:
            continue
        if clean.startswith("term ") or clean.startswith("memory long"):
            continue
        parts = term.split()
        if len(parts) == 1 and parts[0] in generic_labels:
            continue
        if any(
            term in existing
            or (len(existing.split()) >= 2 and existing in term)
            for existing in selected
        ):
            continue
        selected.append(term)
        if len(selected) >= max_terms:
            break
    return selected


def _assign_facets(
    *,
    text: str,
    terms: list[str],
    profile: dict[str, Any],
) -> dict[str, list[str]]:
    seed_terms = profile_facet_seed_terms(profile)
    facets = {name: [] for name in profile_facet_names(profile)}
    lowered = text.lower()
    for facet_name, seeds in seed_terms.items():
        matches = [term for term in terms if any(seed in term or seed in lowered for seed in seeds)]
        if matches:
            facets[facet_name] = matches[:4]
    if not any(facets.values()):
        fallback = terms[:4]
        target = "design_problem" if "design_problem" in facets else next(iter(facets), "")
        if target:
            facets[target] = fallback
    for term in terms[:6]:
        for facet_name in ("method_or_approach", "project_goal", "design_problem"):
            if facet_name in facets and term not in facets[facet_name]:
                if not facets[facet_name]:
                    facets[facet_name].append(term)
                    break
    return facets


def build_semantic_key_index(tree: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    objects: dict[str, Any] = {}
    facet_counts: Counter[str] = Counter()
    term_counts: Counter[str] = Counter()
    for meeting, obj in iter_l1_objects(tree):
        obj_id = str(obj.get("obj_id", "") or "")
        text = _object_text(obj)
        terms = _top_terms(text, profile=profile)
        facets = _assign_facets(text=text, terms=terms, profile=profile)
        for values in facets.values():
            term_counts.update(values)
        facet_counts.update({name: len(values) for name, values in facets.items() if values})
        confidence = min(1.0, 0.25 + 0.08 * sum(len(values) for values in facets.values()))
        objects[obj_id] = {
            "obj_id": obj_id,
            "meeting_id": str(meeting.get("meeting_id", "") or ""),
            "meeting_date": str(meeting.get("meeting_date", "") or ""),
            "type": str(obj.get("type", "") or ""),
            "importance": obj.get("importance", 0.0),
            "semantic_facets": facets,
            "candidate_terms": terms,
            "source_signals": {
                "content": str(obj.get("content", "") or ""),
                "evidence": str(obj.get("evidence", "") or ""),
                "related_topics": list(obj.get("related_topics", []) or []),
            },
            "confidence": round(confidence, 3),
        }
    return {
        "schema_version": SEMANTIC_KEY_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "profile_name": profile.get("name", ""),
        "object_count": len(objects),
        "facet_counts": dict(sorted(facet_counts.items())),
        "top_terms": dict(term_counts.most_common(50)),
        "objects": dict(sorted(objects.items())),
    }


def write_semantic_key_index(
    *,
    share_mem_root: Path | str,
    profile: dict[str, Any],
    out_dir: Path | str,
) -> dict[str, Any]:
    out = ensure_optimization_output(out_dir)
    tree = load_share_tree(share_mem_root)
    index = build_semantic_key_index(tree, profile)
    write_json(out / "semantic_key_index.json", index)
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract optimization v2 semantic keys from L1 evidence.")
    parser.add_argument("--share-mem-root", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    profile = load_profile(args.profile)
    index = write_semantic_key_index(
        share_mem_root=args.share_mem_root,
        profile=profile,
        out_dir=args.out,
    )
    print(f"[optimization:v2] semantic keys written: objects={index['object_count']}")


if __name__ == "__main__":
    main()
