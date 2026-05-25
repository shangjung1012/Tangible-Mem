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
        "This dataset usually has shorter, fragmented English speaker turns. "
        "The same discussion topic may recur across many adjacent short lines, "
        "so preserve continuity across speaker fragments and avoid treating each "
        "short acknowledgement as a separate idea. Downweight pure microphone "
        "checks, jokes, greetings, seating/setup logistics, and local chatter "
        "unless they affect corpus design, annotation, recording procedure, or "
        "data quality. Do not create L1 objects for individual channel "
        "confirmations, normal gain settings, equipment placement, or one-off "
        "setup acknowledgements unless the discussion establishes a reusable "
        "recording rule, corpus-quality issue, or annotation requirement. If a "
        "setup-related item is still worth preserving, keep importance <= 0.55 "
        "unless it defines a repeatable corpus-quality rule or recording "
        "procedure. Do not auto-reclassify decisions from surface words like "
        "proposed, suggested, or considered; classify adoption only from the "
        "bounded evidence. Normalize recurring related_topics when possible: use "
        "annotation data model for database format, XML schema, data format, data "
        "representation, annotation format, stable IDs, and timeline-format "
        "discussions; use recording data quality for durable audio-quality, "
        "breath-noise, and recording-procedure issues. Put the canonical label first "
        "in related_topics, then add only genuinely useful specific subtopics. When "
        "one bounded evidence span contains an unresolved need plus candidate "
        "solutions, avoid creating separate L1 objects from one evidence span unless "
        "the objects answer clearly different durable questions. Do not preserve a "
        "meeting date, participant list, or kickoff as an L1 object unless it changes "
        "a reusable corpus metadata policy or downstream indexing requirement. Do not "
        "preserve microphone inventory, channel mapping, low gain, participant seating, "
        "or device placement unless it changes a reusable recording policy or exposes "
        "a durable data-quality risk. Do not treat a single spoken correction or "
        "disfluency during a reading task as a reusable protocol unless speakers are "
        "explicitly instructed to label such errors. Treat observed task performance "
        "such as actual digit reading, a speaker introduction, headset announcement, "
        "or a one-off correction as source data rather than L1 unless someone states "
        "the instruction, rule, or rationale behind it. Do not create an open issue "
        "from an interrupted agenda or topic handoff unless a durable project, corpus, "
        "or protocol question remains explicit. When the same evidence supports "
        "both a protocol and its rationale, prefer one integrated L1 over separate "
        "approach_change plus argument objects unless the rationale will be useful "
        "independently later."
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
