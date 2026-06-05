from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from optimization.long_term_v2.text_utils import normalize_phrase


PROFILE_DIR = Path(__file__).resolve().parent / "profiles"


def _load_json_compatible_yaml(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"profile must be a JSON object: {path}")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if key == "inherits":
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_profile(path: Path | str) -> dict[str, Any]:
    profile_path = Path(path)
    profile = _load_json_compatible_yaml(profile_path)
    parent_name = profile.get("inherits")
    if parent_name:
        parent_path = PROFILE_DIR / f"{parent_name}.yaml"
        parent = load_profile(parent_path)
        profile = _deep_merge(parent, profile)
    validate_profile(profile, source_path=profile_path)
    return profile


def validate_profile(profile: dict[str, Any], *, source_path: Path | None = None) -> None:
    required = [
        "schema_version",
        "name",
        "domain",
        "semantic_facets",
        "l2_policy",
        "l3_policy",
    ]
    missing = [key for key in required if key not in profile]
    if missing:
        location = f" in {source_path}" if source_path else ""
        raise ValueError(f"profile missing required keys{location}: {missing}")
    facets = profile.get("semantic_facets")
    if not isinstance(facets, list) or not facets:
        raise ValueError("profile.semantic_facets must be a non-empty list")
    names = [str(facet.get("name", "")).strip() for facet in facets if isinstance(facet, dict)]
    if len(names) != len(set(names)):
        raise ValueError("profile.semantic_facets contains duplicate names")


def profile_facet_names(profile: dict[str, Any]) -> list[str]:
    return [str(facet["name"]) for facet in profile.get("semantic_facets", []) if isinstance(facet, dict)]


def profile_facet_seed_terms(profile: dict[str, Any]) -> dict[str, set[str]]:
    seeds: dict[str, set[str]] = {}
    for facet in profile.get("semantic_facets", []):
        if not isinstance(facet, dict):
            continue
        name = str(facet.get("name", "")).strip()
        terms = {
            str(term).strip().lower()
            for term in facet.get("seed_terms", [])
            if str(term).strip()
        }
        if name:
            seeds[name] = terms
    return seeds


def _string_set(values: Any) -> set[str]:
    return {normalize_phrase(str(value)) for value in values or [] if str(value).strip()}


def profile_label_policy(profile: dict[str, Any]) -> dict[str, Any]:
    policy = profile.get("label_policy", {}) or {}
    return policy if isinstance(policy, dict) else {}


def profile_text_policy(profile: dict[str, Any]) -> dict[str, Any]:
    policy = profile.get("text_processing", {}) or {}
    return policy if isinstance(policy, dict) else {}


def profile_type_like_labels(profile: dict[str, Any]) -> set[str]:
    policy = profile_label_policy(profile)
    return _string_set(profile.get("l1_roles", [])) | _string_set(policy.get("type_like_labels", []))


def profile_generic_topic_labels(profile: dict[str, Any]) -> set[str]:
    policy = profile_label_policy(profile)
    return _string_set(policy.get("generic_single_labels", [])) | _string_set(
        policy.get("additional_generic_single_labels", [])
    )


def profile_rejected_topic_labels(profile: dict[str, Any]) -> set[str]:
    policy = profile_label_policy(profile)
    return _string_set(policy.get("reject_exact_labels", [])) | _string_set(
        policy.get("additional_reject_exact_labels", [])
    )


def profile_role_artifact_terms(profile: dict[str, Any]) -> set[str]:
    policy = profile_label_policy(profile)
    return profile_type_like_labels(profile) | _string_set(policy.get("role_artifact_terms", []))


def profile_role_artifact_tokens(profile: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for term in profile_role_artifact_terms(profile):
        tokens.update(part for part in term.split() if part)
    return tokens


def profile_weak_child_terms(profile: dict[str, Any]) -> set[str]:
    policy = profile_label_policy(profile)
    return (
        profile_generic_topic_labels(profile)
        | _string_set(policy.get("weak_child_terms", []))
        | _string_set(policy.get("additional_weak_child_terms", []))
    )


def profile_stopwords(profile: dict[str, Any]) -> set[str]:
    return _string_set(profile_text_policy(profile).get("stopwords", []))


def profile_generic_ngram_terms(profile: dict[str, Any]) -> set[str]:
    return _string_set(profile_text_policy(profile).get("generic_ngram_terms", []))


def profile_max_cjk_token_chars(profile: dict[str, Any]) -> int:
    value = profile_text_policy(profile).get("max_cjk_token_chars", 12)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 12


def profile_token_equivalents(profile: dict[str, Any]) -> dict[str, str]:
    raw = (profile.get("retrieval_eval", {}) or {}).get("token_equivalents", {})
    if not isinstance(raw, dict):
        return {}
    return {normalize_phrase(str(key)): normalize_phrase(str(value)) for key, value in raw.items() if str(key).strip()}


def profile_child_label_normalization(profile: dict[str, Any]) -> dict[str, Any]:
    raw = profile_label_policy(profile).get("child_label_normalization", {})
    return raw if isinstance(raw, dict) else {}
