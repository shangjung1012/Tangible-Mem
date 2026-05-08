"""Dataset-specific incremental extraction presets.

These presets let us tune a small number of knobs for transcript families
without forking the incremental bridge logic. The goal is to preserve the
stable ISCI behaviour while allowing narrower settings for Grace transcripts,
whose lines are longer and denser.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DatasetProfile:
    name: str
    chunk_size: int
    issue_episode_gap_lines: int
    prompt_hint: str


GENERIC_PROFILE = DatasetProfile(
    name="generic",
    chunk_size=40,
    issue_episode_gap_lines=15,
    prompt_hint=(
        "Treat transcript lines as approximate speaker turns. Keep forward_scan "
        "top-down and only use lookback/lookahead when local context is genuinely "
        "missing."
    ),
)

ISCI_PROFILE = DatasetProfile(
    name="isci",
    chunk_size=40,
    issue_episode_gap_lines=15,
    prompt_hint=(
        "This dataset usually has shorter, fragmented conversational turns. The "
        "same issue may recur across many adjacent short lines, so prefer reusing "
        "an existing issue_id before opening a new issue."
    ),
)

GRACE_PROFILE = DatasetProfile(
    name="grace",
    chunk_size=24,
    issue_episode_gap_lines=10,
    prompt_hint=(
        "This dataset usually has longer Mandarin turn-level lines. Each line may "
        "already contain substantial context, so prefer slightly narrower "
        "forward_scan spans and avoid splitting one long turn into multiple issues "
        "or L1 objects unless the topic clearly shifts."
    ),
)

_PROFILE_ALIASES = {
    "auto": "auto",
    "default": "generic",
    "generic": "generic",
    "isci": "isci",
    "icsi": "isci",
    "grace": "grace",
}

_PROFILES = {
    "generic": GENERIC_PROFILE,
    "isci": ISCI_PROFILE,
    "grace": GRACE_PROFILE,
}


def dataset_profile_choices() -> list[str]:
    return sorted(_PROFILE_ALIASES)


def normalize_dataset_profile_name(name: str | None) -> str:
    clean = str(name or "auto").strip().lower()
    if clean not in _PROFILE_ALIASES:
        raise ValueError(f"Unsupported dataset profile: {name}")
    return _PROFILE_ALIASES[clean]


def infer_dataset_profile_name(transcript_path: str | Path) -> str:
    normalized = str(Path(transcript_path)).replace("\\", "/").lower()
    if "/transcript/grace/" in normalized:
        return "grace"
    if "/transcript/isci/" in normalized or "icsi_original_transcripts" in normalized:
        return "isci"
    return "generic"


def resolve_dataset_profile(
    transcript_path: str | Path,
    requested_profile: str = "auto",
) -> DatasetProfile:
    profile_name = normalize_dataset_profile_name(requested_profile)
    if profile_name == "auto":
        profile_name = infer_dataset_profile_name(transcript_path)
    return _PROFILES[profile_name]


def resolve_incremental_settings(
    transcript_path: str | Path,
    *,
    requested_profile: str = "auto",
    chunk_size: int | None = None,
    issue_episode_gap_lines: int | None = None,
) -> dict[str, object]:
    profile = resolve_dataset_profile(transcript_path, requested_profile)

    requested_chunk = int(chunk_size or 0)
    requested_gap = int(issue_episode_gap_lines or 0)

    resolved_chunk = profile.chunk_size if requested_chunk <= 0 else max(1, requested_chunk)
    resolved_gap = (
        profile.issue_episode_gap_lines
        if requested_gap <= 0
        else max(1, requested_gap)
    )

    return {
        "profile": profile,
        "chunk_size": resolved_chunk,
        "chunk_size_source": "profile" if requested_chunk <= 0 else "cli",
        "issue_episode_gap_lines": resolved_gap,
        "issue_episode_gap_lines_source": "profile" if requested_gap <= 0 else "cli",
    }
