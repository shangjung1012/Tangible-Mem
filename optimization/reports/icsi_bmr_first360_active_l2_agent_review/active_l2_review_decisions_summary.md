# Active L2 Review Decisions Summary

- status: `warning`
- generated at: `2026-06-08T20:43:24Z`
- review source: `optimization\runs\icsi_bmr001_031_first360_candidate4_rerun_20260608_c4\manual_review_active_l2\active_l2_manual_review.json`
- decisions source: `optimization\reports\icsi_bmr_first360_active_l2_agent_decisions.jsonl`
- decision count: `25`
- warning issues: `10`
- severe issues: `0`
- validation errors: `0`
- unknown items: `0`

This report is a sidecar review summary. It does not mutate raw L1, active L2/L3, or canonical artifacts.

## Decisions By Type

- `correct`: `12`
- `correct_suppressed`: `3`
- `needs_l3_split`: `2`
- `needs_label_review`: `2`
- `needs_manual_decision`: `3`
- `too_broad_watch`: `3`

## Review Decisions

- `L2-annotation-tool` (active_l2): `needs_l3_split` / `warning` - Representative L1 evidence is durable but spans transcript checking tools, multi-channel timing tools, energy/channel tooling, and synthesis/F0 examples. It should remain active, but the 50 linked L1 suggest this is a topic family candidate rather than one compact L2.
- `L2-data-quality` (active_l2): `too_broad_watch` / `warning` - The evidence is coherent around data quality, but it mixes recording noise, microphone/channel mapping confusion, headset comfort, and external data uncertainty. Keep active, but consider split review if the corpus grows.
- `L2-data-collection` (active_l2): `needs_l3_split` / `warning` - The topic is important and evidence-backed, but 45 linked L1 across 13 meetings includes corpus rationale, digit sessions, and collection logistics. It is likely a parent family for future 30+ meeting runs.
- `L2-data-collection-protocol` (active_l2): `correct` / `none` - Representative L1 consistently discusses collection procedure: written metadata, speaker identification, recording forms, and task protocol tradeoffs.
- `L2-corpus-design` (active_l2): `correct` / `none` - Representative L1 supports a durable topic about corpus design choices, speaker diversity, recording natural meetings, and data-collection target populations.
- `L2-participant-consent` (active_l2): `needs_label_review` / `warning` - Representative L1 is mostly about participant status/background metadata and category design, not consent. The topic may be valid, but the current label is misleading for review and retrieval.
- `L2-corpus-management` (active_l2): `correct` / `none` - Representative L1 consistently discusses corpus distribution, pilot/test recordings, and long-term corpus management goals.
- `L2-analysis-methodology` (active_l2): `too_broad_watch` / `warning` - The topic is plausible but broad: representative L1 includes overlap analysis, participant background analysis, and meeting context concerns. Keep active, but monitor for split pressure.
- `L2-ti-digit` (active_l2): `needs_label_review` / `warning` - Representative L1 clearly concerns TI-digits as an evaluation benchmark and comparison set. The label is too abbreviated and should be clarified, not treated as a wrong topic.
- `L2-asr-performance` (active_l2): `correct` / `none` - Representative L1 consistently covers ASR scoring bugs, error rates, recognizer goals, and distant-microphone recognition performance.
- `L2-data-analysis` (active_l2): `too_broad_watch` / `warning` - The evidence is analysis-related but spans quality triage, location determination, and later result interpretation. It is acceptable as a review target but should not become a generic catch-all.
- `L2-audio-processing` (active_l2): `correct` / `none` - Representative L1 coherently discusses beamforming, noise cancellation, near-field microphone processing, and signal-processing approaches.
- `L2-data-handling` (active_l2): `correct` / `none` - Representative L1 supports a durable handling topic: anonymization, unified forms, and operational treatment of collected data.
- `L2-speech-overlap` (active_l2): `correct` / `none` - Representative L1 consistently covers overlap distribution analysis, scripts, burst patterns, and overlapping-speech collection concerns.
- `L2-digit-reading-task` (active_l2): `correct` / `none` - Representative L1 coherently describes digit-reading task instructions, pacing, error labeling, and data-collection protocol issues.
- `L2-acoustic-modeling` (active_l2): `correct` / `none` - Representative L1 supports a durable modeling topic around speech/non-speech detection, background models, and acoustic model choices.
- `L2-recording-setup` (active_l2): `correct` / `none` - Representative L1 is consistently about physical recording setup, setup time, equipment placement, cabinets, and wire management.
- `L2-audio-quality` (active_l2): `correct` / `none` - Representative L1 coherently covers audio quality issues such as preamplifier noise, microphone uncertainty, and recording quality checks.
- `L2-test-set` (active_l2): `correct` / `none` - Representative L1 consistently discusses test-set construction, randomized order files, misread digits, and handling errors in the digit test set.
- `L2-meeting-agenda` (active_l2): `needs_manual_decision` / `warning` - The topic contains some low-value agenda management, but representative L1 also includes unresolved research issues and follow-up planning. It should be reviewed before suppressing because it may contain planning evidence.
- `L2-go-ahead` (suppressed_l2): `correct_suppressed` / `none` - The label is a discourse phrase and should not be a durable topic. Representative L1 may still be useful, but this L2 label should remain suppressed unless the L1 are reassigned to specific task/protocol topics.
- `L2-annotation-process` (suppressed_l2): `needs_manual_decision` / `warning` - Representative L1 around segmentation correction and annotation trials may be coherent enough for a relabeled active topic. Do not restore automatically, but review before treating suppression as final.
- `L2-little-bit` (suppressed_l2): `correct_suppressed` / `none` - The label is not evidence-backed and representative L1 are heterogeneous. Suppressing this L2 is reasonable while preserving raw L1 evidence elsewhere.
- `L2-system-performance` (suppressed_l2): `needs_manual_decision` / `warning` - Representative L1 includes ASR adaptation performance and text retrieval indexing. The current label is broad and may mix separate durable topics, so it needs review rather than automatic restore or permanent suppression.
- `L2-team-decided` (suppressed_l2): `correct_suppressed` / `none` - The label is type-like and not a durable topic. Individual decisions may be important, but the topic label should remain suppressed unless reassigned by evidence-backed semantic topics.
