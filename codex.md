# Codex Long-Term Handoff

Last updated: 2026-05-10 Asia/Taipei

This file is the canonical handoff state for continuing `long_term/` work across devices and across the selected forked Codex chats. Treat older or out-of-focus Codex sessions as historical evidence, not as equally current instructions. If a forked chat conflicts with this file or the current repo, prefer the current repo plus this file.

Do not commit `.env`, API keys, credential paths, `~/.codex/auth.json`, or raw Codex JSONL histories.

## Long-Term Current State

- Repository canonical state is the current `main` branch plus this handoff file; device-specific local worktree artifacts are tracked separately below.
- `share_mem/` is the new canonical L1 store for shared short-term and long-term memory work. Rebuild it from Grace transcripts with `uv run share_mem/build_tree.py --transcript-dir meeting_recording/transcript/grace --output-root share_mem --mode multi-agent --dataset-profile grace --model gemini-2.5-pro --taxonomy v2-memory-roles --include-legacy-type --clean`.
- Canonical multi-agent L1 extraction code now lives under `share_mem/l1/`. `long_term/` keeps the active recall surface plus the generated L2 view entrypoints; the old temporal L1/L2/L3 pipeline is archived.
- `long_term/tree.json` is now archived under `long_term/archive/legacy_temporal_l2_l3/tree.json`, not the source of truth for new L1 recall. New L2 work should use `share_mem/tree.json` or `share_mem/meetings/` as its L1 base.
- The current L1 research mainline is still multi-agent extraction. `full` / `monolithic` and `incremental` remain baselines or references, not the primary development path.
- Multi-agent L1 is a staged prompt pipeline, not autonomous long-lived agents: `prior_context_pack -> context_planner -> segmentation -> repair/coarsening -> boundary refinement -> idea units -> extraction packets -> bounded type agents -> grounding -> conflict resolution -> verifier -> reducer -> persist L1 -> relation/activity sidecars`.
- Canonical Grace L1 currently uses v2 memory roles in `type`: `decision`, `action_item`, `open_issue`, `proposal`, `argument`, `finding`, and `approach_change`.
- `legacy_type` is retained on canonical Grace L1 objects for compatibility diffing and rollback checks only.
- Additional L1 type experiments should still write to separate `share_mem_experiments/...` roots and be compared before promotion.
- The first active L2 view is implemented under `long_term/l2/`: build with `uv run long_term/cli.py build-l2-view --share-mem-root share_mem --output-root long_term/l2 --mode deterministic --clean`, then validate with `uv run long_term/cli.py validate-l2-view --share-mem-root share_mem --root long_term/l2 --out long_term/l2/validation`.
- `long_term/l2/l2_view.json` and `long_term/l2/l2_index.json` are generated views over clean immutable L1 evidence. They do not replace `share_mem/tree.json`, and the builder may intentionally leave low-value or isolated L1 objects unlinked.
- The first `share_mem` topic-tree implementation remains experimental / append-only sidecar. It can be built with `uv run share_mem/build_topic_view.py --tree share_mem/tree.json --mode hybrid --model gemini-2.5-pro`, but the active long-term topic layer is now `long_term/l2/`; root-level `share_mem/topic_tree.json`, `topic_updates/`, and `topic_index.json` are not required for the current canonical handoff and may be absent when `manifest.json` reports `topic_view.exists=false`.
- Topic-tree remains a view, not the canonical raw L1 store. `share_mem/tree.json` and `meetings/<meeting_id>.json` remain immutable evidence; topic state is rebuildable from `topic_updates/`.
- Recall starts from L1 retrieval over `share_mem/tree.json`, always includes a compact global topic map, then expands upward through materialized L3 child L2 context when `long_term/l3/l3_index.json` covers a seed. The live app path still defaults to semantic L1 retrieval; retrieval eval can use `--no-llm --retrieval-mode lexical` for deterministic offline smoke tests. If no materialized child L2 exists, recall falls back to `long_term/l2/l2_index.json` and `long_term/l2/l2_view.json`. Temporal parent-chain expansion is legacy fallback only.
- Multi-agent quality, recurrence, relation, and activity metadata live in sidecars such as `l1_quality_index.json`, `memory_relations_index.json`, and `memory_activity_index.json`; the canonical L1 schema remains clean.
- Multi-agent research logs now include structured `api_calls/` artifacts in addition to `prompts/` and `responses/`; keep them out of commits when they contain raw prompts/responses or sensitive local paths.
- Legacy `summarize phase`, `bridge`, `build-tree`, and old temporal snapshots are archived under `long_term/archive/legacy_temporal_l2_l3/` for historical reference only.
- Local generated stores and research outputs such as embedding caches, incremental DBs, Grace outputs, and research logs are working artifacts unless explicitly promoted through documentation.
- Topic-tree remains a sidecar/view only. The active long-term L2 topic view now lives under `long_term/l2/`; future L3 work should build on `share_mem` L1 plus this L2 view unless a later evaluation explicitly promotes another structure.
- `short_term/` is currently out of scope for this `long_term` architecture cleanup. Do not include short-term context loading or short-term workflow changes in the current long-term refactor.
- Formal UI work is deferred. The next mainline should converge the memory model and recall path first; UI/debug viewers should stay prototype tooling until recall behavior is stable.
- Human-in-the-loop review should use sidecar editing: keep raw L1 evidence immutable and write corrections, review decisions, or accepted replacements as separate sidecar artifacts. Do not directly edit existing evidence objects inside `share_mem/tree.json`.
- The current active L3 definition is overflow promotion above L2: when an L2 topic grows too broad, promote that topic into an L3 parent and split its contents into multiple new L2 child topics. L3 is therefore a higher topic container, not a singleton project profile and not a replacement for raw L1.
- L3 promotion design is summarized in `doc/l1_l2_update_retrieve_flow.md`. The helper `long_term/l3_promotion.py` is sidecar-only: it detects overcrowded L2 candidates and builds promotion records without rewriting L2 artifacts or raw L1 evidence.
- The old local L2 prototype/sidecar experiments now live under `long_term/archive/prototype_l2_threads/` and `long_term/archive/prototype_memory_ui/`, not the active production path. They are not exposed through `long_term/cli.py`; their archived tests document prototype behavior only.

## Windows Local Worktree State

- On this Windows device, the local worktree has untracked local artifacts: `04_08_bridge_test_results.json`, `agents.md`, and `test_bridge.py`.
- Treat those files as local working artifacts unless a future update explicitly promotes them through docs or a reviewed commit.
- The partial Grace run under `long_term/grace output/...0307_multi_agent` reports `argument` and `open_question` as deferred. That artifact is stale: current repo code and tests include both types in the bounded type-agent loop.
- `uv run python -m unittest discover -s tests` currently hits a short-term Windows shell-script execution issue (`WinError 193` from trying to execute a `.sh` file directly). Track this as a separate short-term Windows test hygiene follow-up, not as a blocker for the long-term L2/L3 work.

Useful commands:

```bash
uv sync
uv run share_mem/build_tree.py --transcript-dir meeting_recording/transcript/grace --output-root share_mem --mode multi-agent --dataset-profile grace --model gemini-2.5-pro --taxonomy v2-memory-roles --include-legacy-type --clean
uv run long_term/cli.py --help
uv run long_term/cli.py build-l2-view --share-mem-root share_mem --output-root long_term/l2 --mode deterministic --clean
uv run long_term/cli.py validate-l2-view --share-mem-root share_mem --root long_term/l2 --out long_term/l2/validation
uv run long_term/cli.py validate-l3-view --share-mem-root share_mem --l2-root long_term/l2 --l3-root long_term/l3 --out long_term/l3/validation
uv run python long_term/evaluate_retrieval.py --queries long_term/eval/long_term_retrieval_queries.jsonl --out long_term/eval --no-llm --retrieval-mode lexical
uv run long_term/cli.py build-l2-view --help
uv run long_term/cli.py validate-l2-view --help
uv run python -m unittest discover -s tests
```

## Merged Task Board

| Status | Priority | Task | Canonical next step |
| --- | --- | --- | --- |
| done | P0 | Curate retrieval eval expected L1 ids and fix all-zero L1 recall. | Demo queries now keep `strict_gold_obj_ids` for older exact seeds and use current `expected_obj_ids` for acceptable L1 evidence scoring. Offline lexical eval is no longer all-zero. |
| done | P1 | Tune remaining offline retrieval eval L2 misses. | L2 ranking now gives query-label similarity enough weight that the long-term retrieval and manager-agent eval queries select the expected L2 topics without sacrificing acceptable L1 recall or prompt-budget pass rate. |
| active | P1 | Validate current multi-agent L1 plus sidecars on real Grace/ICSI meetings. | Run a small repeatable set, inspect `status.json`, `run_summary.json`, `metrics_summary.json`, `l1_quality_index.json`, relation/activity sidecars, and final `tree.json` diffs. |
| active | P2 | Keep multi-agent cost and failure visibility under control. | When a run is slow or interrupted, inspect per-run `status.json` and `run_summary.json` first. Add targeted fixes only where artifacts show a bottleneck. |
| active | P2 | Fix Windows full unittest short-term script launch. | `tests/test_short_term_snapshot_update.py` currently tries to execute a `.sh` script directly on Windows and raises `WinError 193`. This is short-term Windows test hygiene, not a blocker for long-term L2/L3 work. |
| done | P0 | Materialize reviewed L3 promotions above the current L2 topic view. | Deterministic `build-l2-view` now writes `l3_promotions.json`, `l3_view.json`, `l3_index.json`, and `l2_merge_review.json` without mutating raw L1 evidence or active L2 artifacts. |
| done | P0 | Merge the selected long-term Codex chats into one canonical handoff flow. | Use this `codex.md` as the single entrypoint for future chats. |
| done | P0 | Rebuild canonical L1 under `share_mem/` from Grace transcripts. | Current canonical Grace `share_mem` has 7 meetings and 509 v2 L1 objects with `legacy_type` compatibility metadata. |
| done | P0 | Add active share_mem-based L2 view under `long_term/l2`. | Current L2 topic view has 15 topics, 477 linked L1 objects, 32 intentionally unlinked or low-signal L1 objects, and 0 severe validation issues. |
| done | P0 | Wire active recall to the new `long_term/l2` upward context. | `long_term/recall.py` now starts from semantic L1 hits in `share_mem/tree.json`, includes a compact global topic map, prefers materialized child L2 context via `l3_index.json`, and falls back to sliced active L2 context when needed. Missing L2 assignments are non-fatal. |
| done | P1 | Tighten recall behavior around L1 -> L2/L3 parent-chain context. | The prompt formatter is now evidence-first: Global Topic Map, L1 Evidence Seeds, L2 / Child-L2 Evolution Context, and optional Retrieval Debug. Large topics are sliced instead of injected whole. |
| done | P1 | Adopt semantic L1 retrieval with parent-chain expansion. | Current code and `doc/l1_l2_update_retrieve_flow.md` are the source of truth; archived retrieve plans have been removed from active docs. |
| done | P1 | Adopt compact L2/L3 schema. | Active L2/L3 are generated sidecars over `share_mem` L1; temporal artifacts remain archived history. |
| done | P2 | Keep incremental bridge as a reference path. | SQLite issue tables are working state for incremental mode only; do not migrate `tree.json` to SQL just because incremental mode uses SQLite internally. |
| superseded | P0 | Maintain four separate Codex room roles for long-term work. | Replaced by one canonical long-term handoff plus focused thread lineage below. |
| superseded | P2 | Treat forked chats as current independent plans. | Forks must be summarized here before they can steer implementation. |

## Focused Thread Lineage

Only the following selected Codex chats should steer future `long_term/` work. Other local sessions can still be searched privately if needed, but they are not part of the active handoff unless a conclusion is summarized back here.

| Thread / fork | Status | Capsule |
| --- | --- | --- |
| `019df723` - `分析長期架構邏輯` | merged | High-level architecture review concluded: multi-agent is strongest in traceability, bounded scope, deterministic guardrails, and schema compatibility; weak points are cost, run resumption/failure closure, type ambiguity, relation depth, and using rich sidecar signals in L2/L3/recall. Later work addressed several of these through status/run summary and sidecars. |
| `019df88d`, `019df912`, `019dfa5f` - incremental/multi-agent forked work | merged as historical forks | These large forked histories include incremental bridge implementation, run checks, pushes, and long-running multi-agent status checks. Use current repo/docs, not raw fork instructions, for implementation decisions. |
| `019dfc8f` - `評估 L2/L3 主題樹方案` | open branch | Proposed replacing or complementing time-based L2/L3 with topic-oriented trees where objects append over time. Latest clarification: the safer shape is a topic tree plus separate meeting timeline nodes, not pure topic trees. Not adopted yet. Main unresolved question: can this hybrid improve retrieve precision while preserving meeting flow and temporal context better than current L1 retrieval plus temporal parent chain? |

## Recent L2/L3 Topic-Tree Discussion

This is the latest design clarification from the 2026-05-07 discussion and should be read before changing `schema.py`, `summarize.py`, or `recall.py`.

### Proposed Meaning Of L1/L2/L3

- `L1` remains an immutable, evidence-grounded memory object extracted from one meeting segment. It keeps `meeting_id`, timestamp/date, evidence text, and ideally line/span metadata where available.
- `L2` in the topic-tree proposal is not a time phase. It is a subtopic or state node inside a topic tree, such as `L2/L3 organization`, `upward retrieve`, `forgetting policy`, or `precision-recall evaluation`.
- `L3` in the topic-tree proposal is not one singleton project profile. It is the root of one major topic tree, such as `long-term memory architecture`, `retrieval strategy`, `evaluation method`, or `poster/demo planning`.
- A separate project/topic overview may still exist, but it should not be treated as the only L3 if the topic-tree design is adopted.

Example shape:

```text
L3: 長期記憶架構
  L2: L2/L3 組織方式
    L1: 0507 討論從時間 phase 改成主題樹
    L1: 0507 討論 object append 而不是 overwrite
  L2: retrieve 策略
    L1: 0507 討論往上 retrieve 要帶出 L2/L3
```

### Why Retrieve Upward To L2/L3

- L1 is the concrete evidence point; L2/L3 provide the explanatory frame.
- Upward retrieval helps avoid isolated answers: a matched object can be explained as part of a larger subtopic and long-running topic.
- For complex questions such as "why did this mechanism change?" or "how did retrieval evolve?", L2/L3 can provide current state, prior alternatives, and causal progression instead of a flat list of L1 hits.
- If L2/L3 are topic-based, parent context should usually be same-topic rather than same-time-window, reducing irrelevant context from other topics discussed in the same meeting.

### Meeting Context Must Not Disappear

Pure topic trees are not enough. If one meeting's objects are scattered into different topic trees, the system may lose the answer to "what was the previous meeting mainly doing?"

The safer design is two coordinated views:

```text
Meeting timeline view:
  Meeting 0507
    direction/summary: this meeting shifted from time-based L2/L3 toward topic-tree L2/L3, while raising concern about losing meeting-level context.
    ordered_object_ids: [obj1, obj2, obj3, obj4]
    topic_ids: [long_term_memory_architecture, retrieval_strategy, meeting_context]

Topic tree view:
  L3 long_term_memory_architecture
    L2 topic_tree_design
      obj1, obj2
  L3 retrieval_strategy
    L2 upward_context_expansion
      obj3
```

In other words, every L1 object needs two coordinates:

- `meeting coordinate`: where it occurred in the original meeting flow.
- `topic coordinate`: which long-running topic/subtopic it updates.

Recall should choose the view based on query intent:

- "上一場 meeting 大方向在做什麼？" should retrieve meeting nodes/timeline summaries.
- "retrieval 機制怎麼演進？" should retrieve topic tree state and relevant timeline events.
- "這個決定當時是在什麼脈絡下講的？" should retrieve the L1 object, nearby meeting context, and the relevant topic L2/L3 state.

## Focused Thread Details

### `019df723` - Architecture Review

Use this thread as the high-level map of why `long_term/` is shaped this way.

Key conclusions:

- The core architecture is still a canonical temporal memory tree stored in `tree.json`; multi-agent is the main L1 producer, not a replacement for all storage, summarize, and recall logic.
- Multi-agent L1 exists to make extraction inspectable. Its value is not merely "more agents"; it is bounded scope, artifacts at each stage, deterministic checks, and evidence-grounded reduction.
- The important pipeline idea is: fixed windows provide stable coordinates, segmentation and repairs prevent skipped transcript lines, idea units become shared intermediate evidence, typed agents extract candidate L1 objects, and grounding/verifier/reducer decide what survives.
- The strongest properties are traceability, bounded extraction, deterministic guardrails, and compatibility with the existing L1/L2/L3 schema.
- The recurring weak points are API cost/latency, stage failure visibility, type ontology ambiguity, cross-meeting relation depth, and how much rich sidecar metadata should influence L2/L3/recall.

What later work already improved:

- `argument` and `open_question` are now part of the bounded type-agent loop.
- `status.json` and `run_summary.json` make interrupted or failed multi-agent runs easier to inspect.
- `l1_quality_index.json`, `memory_relations_index.json`, and `memory_activity_index.json` let summarize/recall use quality and cross-meeting signals without polluting canonical L1 objects.
- Compact L2/L3 schemas reduced the old "L3 equals flattened L2 equals flattened L1" problem.

Still relevant warnings:

- Do not optimize prompts blindly. First inspect the run artifacts and identify whether the failure is segmentation, idea units, type candidates, grounding, verifier, reducer, relation linking, or recall formatting.
- Do not treat sidecars as hidden canonical truth. They can weight and explain, but `tree.json` remains the durable source of memory objects.
- If a future change touches L1 type definitions, update the bridge producers, verifier, reducer, summarize prompts, recall formatting, tests, and docs together.

### `019df88d` / `019df912` / `019dfa5f` - Incremental And Multi-Agent Forks

Use these threads as implementation history, not as the current mainline.

What they established:

- Incremental bridge was added as a side path with minimal architectural disruption. It uses SQLite as working state for transcript lines, issue tracking, issue mentions, and draft L1 candidates.
- The final output still goes through the existing normalization and insertion path into `tree.json`; SQLite is not the long-term canonical store.
- The issue table is a temporary extraction aid: it helps the incremental extractor remember repeated topics while scanning a transcript, but it is not the same as L2/L3 memory.
- The correct design principle was "reuse existing contracts": current L1 schema, all 6 object types, importance calibration, todo normalization, and `bridge` CLI behavior should stay aligned.
- Function-calling orchestration had a practical constraint: preserve Gemini function call IDs when returning function responses, because helper APIs may not expose all fields cleanly across SDK versions.

Current canonical interpretation:

- `--mode multi-agent` is the research mainline for L1 extraction.
- `--mode incremental` is a useful baseline/reference and debugging comparison point, especially when reasoning about tool-calling, issue tables, and long transcript scanning.
- `--mode full` / `--mode monolithic` remains a baseline for comparing whether staged extraction improves evidence quality enough to justify cost.

What to check before reviving this fork:

- Confirm whether the problem is really solved better by incremental tool-calling than by the current multi-agent artifacts.
- Inspect `long_term/archive/legacy_temporal_l2_l3/incremental_store.py`, `long_term/archive/legacy_temporal_l2_l3/gemini_incremental_extractor.py`, `long_term/archive/legacy_temporal_l2_l3/bridge.py`, and `long_term/archive/legacy_temporal_l2_l3/dataset_profiles.py` before changing legacy behavior.
- Keep `tree.json` as canonical unless there is a separate storage migration plan with tests and rollback.
- If incremental mode is used for evaluation, compare output quality against multi-agent on the same transcript set and report both accepted L1 objects and rejected/low-confidence candidates.

### `019dfc8f` - Topic-Tree Open Branch

Use this thread as the active design fork to evaluate next.

Proposal:

- Current retrieve starts from an L1 match and brings in the L2/L3 parent from the same temporal phase/project profile.
- The topic-tree idea would add or replace that upward path with topic-oriented thread trees: one meeting's objects can be distributed across multiple topic threads, and future objects append as new timestamped events under the same topic.
- In this proposal, L2 is a subtopic/state node and L3 is a major topic root. There can be many L3 topic roots, not only one singleton project profile.
- Old L1 objects should remain append-only and evidence-grounded. The dynamic part should be the topic thread's `current_state`, `timeline_digest`, or topic-level summary, not the original L1 evidence object.
- Meeting-level context must stay available through a separate meeting timeline/node view that records the meeting's direction, ordered object IDs, and touched topic IDs.

Expected benefits:

- Higher retrieve precision for "how did this topic evolve?" questions, because parent context would be same-topic rather than same-time-window.
- Better preservation of evolution: early hypotheses, later changes, abandoned alternatives, and current state can coexist instead of being overwritten by a summary.
- Cleaner global project memory: multiple L3 roots can each hold an active topic state instead of forcing every topic into one flattened profile.
- Stronger answers to "why" questions, because a topic thread can connect decisions, arguments, method changes, results, and open questions across meetings.
- Better query routing: meeting-direction questions can use meeting nodes, while cross-meeting evolution questions can use topic trees.

Main risks:

- Topic clustering can split one real topic into multiple trees or merge unrelated topics. Either mistake hurts recall more subtly than temporal phases.
- A single meeting's flow becomes harder to reconstruct if its objects are scattered across topic trees without a preserved meeting timeline.
- Append-only topic history can bloat prompts unless it separates raw event history, compact timeline digest, and current state.
- Topic state can duplicate relation/activity sidecars if the responsibilities are not clear.
- Replacing temporal L2/L3 too early would disturb summarize, recall, snapshots, and evaluation without proof.

Evaluation question:

- Compare current retrieval (`semantic L1 -> temporal L2/L3 parent chain -> relation/activity soft expansion`) against a proposed hybrid path (`semantic L1/topic search -> topic thread -> current state + relevant event timeline`, plus meeting node retrieval for meeting-direction questions).
- Measure whether topic retrieval improves precision and explanation quality while the meeting timeline still answers "what was that meeting mainly doing?"
- Treat the first implementation as an additional sidecar/view unless the comparison clearly shows it should replace temporal L2/L3.

## Design Decisions

- `codex.md` is the canonical cross-device handoff; raw Codex JSONL is private backup only.
- Keep `share_mem/tree.json` as the canonical L1 store. `long_term/archive/legacy_temporal_l2_l3/tree.json` is a legacy temporal artifact and SQLite remains working state for archived incremental extraction only.
- Keep old temporal L2/L3 as legacy context only. The active generated L2 topic view is `long_term/l2/`, built from `share_mem` L1.
- Keep `short_term/` out of the current `long_term` refactor. Any short-term integration should wait until the long-term memory model and recall path are stable.
- Retrieve should start from L1 because L1 has concrete evidence. New L1 retrieval reads `share_mem/tree.json`; active upward expansion uses `long_term/l2/l2_index.json` and `long_term/l2/l2_view.json`.
- Preserve meeting flow by keeping temporal containment or explicit meeting timeline nodes available even if topic-oriented views are later added.
- Define L3 as overflow promotion above L2: when an L2 topic becomes too broad, promote it into an L3 container and split its evidence into multiple L2 child topics. Keep any global project/topic overview separate from L3.
- Keep L3 promotion sidecar-first until a reviewed splitter exists. `long_term/l3_promotion.py` may identify candidates and build records, but must not rewrite `l2_index.json`, `l2_view.json`, or raw `share_mem` evidence.
- A topic-tree implementation must not make old L1 objects mutable. Append new timestamped topic events/state versions and update only materialized topic-level state/digests.
- HITL corrections must use sidecar editing. Keep raw L1 immutable and do not directly modify existing evidence objects in `share_mem/tree.json`; record review patches, corrections, or accepted replacements in sidecar files that can be replayed or audited.
- Defer formal UI implementation. Use lightweight debug artifacts only where they support model/recall evaluation; do not promote viewer prototypes to the active path before recall is settled.
- `share_mem/topic_updates/` is the source of truth for topic evolution. `share_mem/topic_tree.json` and `share_mem/topic_index.json` are rebuildable materialized views.
- `long_term/l2/` is a generated long-term L2 topic view, not the raw evidence store. It can intentionally omit low-value or isolated L1 objects; validator review queues should catch important misses.
- `long_term/archive/prototype_l2_threads/` and `long_term/archive/prototype_memory_ui/` contain prototype/sidecar artifacts. The active path is `long_term/cli.py build-l2-view` and `validate-l2-view`, backed by `long_term/build_l2_view.py`, `long_term/validate_l2_view.py`, and `tests/test_l2_view.py`.
- Keep L1 object schema clean and put quality/relation/activity metadata in sidecars. Sidecars may influence summarize/recall conservatively but should not become hidden canonical truth.
- Treat `argument` as an independent L1 object for now because it helps answer "why did we decide this?" without bloating `decision` / `method_change` content.
- Use compact L2/L3 prompt context. Avoid reintroducing large flattened method timelines unless a benchmark shows recall quality needs them.
- Do not let previous-memory context become evidence for new L1 extraction. Old memory can disambiguate, but current transcript lines must ground new objects.
- Forks can propose alternatives, but only this file can promote one branch to canonical next work.

## Dynamic Update Rules

Future Codex chats should update this file directly when their work changes the canonical handoff state.

Update `codex.md` when:

- An active task is completed, blocked, superseded, or split into clearer next steps.
- A design decision is adopted, rejected, or materially revised.
- A forked thread becomes canonical, is demoted to historical context, or needs a new evaluation question.
- A run or test produces evidence that changes the next implementation step.
- A new cross-device handoff is needed after code changes, experiments, or long design discussion.

How to update:

- Edit the smallest relevant section instead of rewriting the whole file.
- Keep `Merged Task Board` aligned with the actual next action.
- Add or adjust `Focused Thread Details` only when the selected thread interpretation changes.
- Add a dated entry under `Handoff Log` at the end of each meaningful work session.
- Keep secrets out: never write `.env` values, API keys, real credential paths, service-account JSON, or raw Codex JSONL into this file.
- Keep repo canonical state separate from local device/worktree artifacts; local untracked files can be noted, but they are not canonical unless promoted through docs or commit.
- Stale run artifacts can inform debugging, but they must not override current repo code, current tests, or `Design Decisions`.
- If current repo code disagrees with a previous note in this file, inspect the code and update the note instead of carrying both as equal truth.
- If the change is exploratory and no canonical state changed, leave `codex.md` untouched and just report findings.

## Topic-Tree Evaluation Checklist

Before implementing the topic-tree branch as canonical schema, write down the comparison result for these questions:

- Retrieval precision: for topic-evolution questions, does topic-thread expansion return less irrelevant context than temporal L2/L3 parent-chain expansion?
- Meeting continuity: can the system still answer "what happened in this meeting?" after one meeting's L1 objects are distributed across multiple topics?
- Meeting direction: can the system answer "what was the previous meeting mainly doing?" without reconstructing it from scattered topic nodes?
- Evidence preservation: are old L1 objects still immutable and grounded to their original transcript lines?
- State separation: does the design clearly separate raw events, topic `current_state`, compact `timeline_digest`, and optional topic overview?
- Coordinate separation: does each L1 object keep both meeting coordinates and topic coordinates?
- Sidecar boundary: does topic state complement `memory_relations_index.json` / `memory_activity_index.json`, or does it duplicate them?
- Prompt budget: can retrieval include only the latest topic state and a short relevant timeline instead of the full append-only history?
- Migration cost: what code must change in summarize, recall, snapshots, tests, and docs if topic tree replaces temporal L2/L3?
- Promotion rule: start as a sidecar/view; promote to canonical only if it improves retrieve quality without losing temporal flow.

## Next Prompt

Use this prompt when starting the next Codex chat on this project:

```text
請先讀 repo 根目錄的 codex.md、README.md、long_term/README.md，然後跑 git status --short --branch。這個專案之前有幾個選定的 Codex 聊天室平行討論 long_term 任務，其中有些是 fork 出去的分支；請以 codex.md 的 Focused Thread Lineage 和 Focused Thread Details 為 canonical state，不要把舊 fork 或未列出的 session 當成同等最新狀態。

你的任務是接續 long_term 的目前主線：先確認 Merged Task Board 裡 active 的最高優先項，再讀相關 long_term 程式與測試。若發現舊討論和目前程式碼不一致，以目前 repo 和 codex.md 的 Design Decisions 為準。

如果這次工作改變了 canonical 狀態，請直接更新 codex.md：更新 Merged Task Board、Design Decisions、Focused Thread Details 或 Topic-Tree Evaluation Checklist 中相關段落，並在 Handoff Log 追加本次完成、未完成、下一步、任何被 supersede 的舊分支。若只是探索且沒有改變 canonical 狀態，請不要修改 codex.md，只在回覆中說明原因。
```

## History Handling

Private backup may include:

- `~/.codex/session_index.jsonl`
- `~/.codex/sessions/**/*.jsonl`
- `~/.codex/archived_sessions/*.jsonl`

Do not back up or commit:

- `~/.codex/auth.json`
- `.env`
- API keys
- service-account JSON files
- real credential paths
- raw Codex JSONL inside this repository

Cross-device restore rule:

- A new device should be able to continue with `git clone`, a locally recreated `.env`, `uv sync`, and this file.
- If raw history is needed, search the private backup manually and summarize any useful conclusion back into `codex.md`.
- Do not depend on Codex UI session import as the only handoff mechanism; session formats and local auth state can change.

## Handoff Log

### 2026-05-10 - Converge Offline Retrieval Eval And L3 Child Split

- Retrieval eval now supports true deterministic `--no-llm --retrieval-mode lexical`: it uses a heuristic recall plan and lexical L1 retrieval, without calling Gemini planner, embeddings, or a final answer LLM.
- Demo eval gold now separates historical `strict_gold_obj_ids` from current acceptable `expected_obj_ids`. The current 8-query, 32-run offline grid reports acceptable L1 recall 1.0, strict historical L1 recall 0.0833, L2 hit rate 1.0, L3 hit rate 1.0, and prompt-budget pass rate 1.0.
- The transcript segmentation L3 split now has 8 deterministic child L2 topics: fixed vs dynamic chunking, window and boundary selection, tool-calling transcript reading, idea-unit generation, missing-line coverage, repair/coarsening, cross-window continuity, and evidence grounding/line coverage.
- Current generated L3 state: 2 L3 parents, 11 materialized child L2 topics, and 184 assigned L1 objects. L3 validation reports 0 severe issues, 0 unassigned L1, 0 duplicate assignments, and 11 warnings, all `needs_retrieval_slice` prompt-budget diagnostics rather than oversized child L2 failures.
- The L2 topic-selection miss on the long-term retrieval and manager-agent eval queries was fixed by increasing query-label similarity influence during L2 ranking while keeping topic-size penalty as a prompt-budget safety signal.

### 2026-05-09 - Add Layered L3 Retrieval And Validation

- `build-l2-view` now defaults to deterministic L3 sidecar generation and writes `long_term/l3/l3_promotions.json`, `l3_view.json`, `l3_index.json`, and `l2_merge_review.json`.
- Current generated L2 state: 7 Grace meetings, 509 L1 objects, 15 L2 topics, 477 linked L1 objects, and 32 unlinked low-signal/isolated L1 objects.
- Current generated L3 state: 2 L3 parents, 6 materialized child L2 topics, and 184 assigned L1 objects. Promotion coverage validation reports 0 unassigned L1, 0 duplicate assignments, and 0 invalid `l3_index` references.
- L3 validation reports 0 severe issues and 8 warnings. The warnings are child-size / retrieval-slice diagnostics: two child L2 nodes under transcript segmentation are still large enough to deserve future split review, but prompt formatting slices them instead of injecting the full timeline.
- Retrieval is now always-on layered for meeting-memory queries: L1 evidence seeds first, compact Global Topic Map always present, materialized child L2 preferred through `l3_index`, active L2 fallback when needed, and optional debug metrics for tests/eval.
- The first retrieval eval smoke report uses 8 demo-safe queries. It currently has L2 hit rate 0.875, L3 hit rate 1.0, prompt budget pass rate 1.0, and expected L1 recall 0.0 because the demo expected L1 ids are stale and need curation from selected seed ids.

### 2026-05-09 - Harden L1/L2 Quality Gates After Full Grace Rerun

- Full Grace live rerun produced 7 canonical meetings and 509 v2 L1 objects under `share_mem/`, with `legacy_type` retained for compatibility.
- L1 comparison against the 545-object checkpoint reports 0 high-importance unmatched and 0 watchlist unmatched after matcher anchor fixes for evaluation, code-driven LLM control, style-prompting, API budget, mentor-dialogue source, and STM/LTM reactivation rewordings.
- Rebuilt `long_term/l2/` from the new `share_mem` tree: 16 L2 topics, 449 linked L1 objects, 60 unlinked L1 objects, and 0 severe validation issues. Remaining 15 warnings are manual-review diagnostics, not schema blockers.
- The old root-level `share_mem` topic-tree sidecar was not promoted after the full rerun. A full `build_topic_view.py --mode hybrid` rebuild is too slow for the current quality loop and timed out locally after one hour, so active topic context should come from `long_term/l2/`.
- Verification for this checkpoint: `uv run share_mem/compare_l1_runs.py --baseline share_mem_experiments/full_rerun_baseline_20260509_124443/tree.json --candidate share_mem/tree.json --out share_mem_experiments/full_rerun_comparison_after_rule_fix_20260509_124443`, `uv run long_term/build_l2_view.py --share-mem-root share_mem --output-root long_term/l2 --mode deterministic --clean`, `uv run long_term/validate_l2_view.py --share-mem-root share_mem --root long_term/l2 --out long_term/l2/validation`, and `uv run python -m unittest discover -s tests`.

### 2026-05-09 - Design L3 Promotion Rule

- Added L3 promotion design to `doc/l1_l2_update_retrieve_flow.md`: overcrowded L2 topic -> L3 parent -> two or more child L2 topics.
- Documented candidate thresholds, sidecar promotion record shape, old L2 -> new L3 + child L2 mapping, `l2_index` / `l2_view` compatibility strategy, and raw L1 immutability requirements.
- Added `long_term/l3_promotion.py` as a minimal sidecar-only helper for candidate metrics, promotion review decisions, and promotion record construction.
- Added `tests/test_l3_promotion.py` covering large/small L2 decisions, mapping shape, and non-mutation of inputs.

### 2026-05-09 - Wire Recall To Active L2 View

- Updated `long_term/recall.py` so the main long-term recall path is `share_mem/tree.json` semantic L1 hit -> `long_term/l2/l2_index.json` L2 assignment -> `long_term/l2/l2_view.json` compact topic context.
- Prompt formatting now emits `=== L2 主題脈絡 ===` for active L2 topic nodes with current state, matched L1 ids, and compact timeline digest. Legacy temporal phase formatting remains as fallback.
- Updated `app/memory_context.py` to pass the active L2 index/view paths into recall. `short_term/` remains untouched and out of scope.
- Added `tests/test_recall_l2_view.py` covering L1 -> L2 expansion, missing L2 fallback behavior, and prompt formatting with new L2 information.

### 2026-05-09 - Archive L2 Prototype Files

- Moved L2 thread/topic prototypes into `long_term/archive/prototype_l2_threads/`.
- Moved the static memory debug viewer prototype into `long_term/archive/prototype_memory_ui/`.
- Moved the corresponding prototype tests into the archive folders and updated their `sys.path` setup so they remain runnable as archived checks without re-exporting prototype modules from active `long_term/`.
- Updated `long_term/README.md` and `long_term/archive/README.md` so the active path stays focused on `share_mem`, `long_term/build_l2_view.py`, `long_term/validate_l2_view.py`, and recall modules.

### 2026-05-09 - Document L2 Prototype Cleanup Boundary

- Recorded the current long-term architecture boundary: `short_term/` is out of scope, formal UI is deferred, HITL uses sidecar editing, and raw `share_mem/tree.json` L1 evidence remains immutable.
- Clarified the active L3 definition: if an L2 topic grows too broad, it should be promoted into an L3 parent and split into multiple new L2 child topics.
- Classified the old `long_term/l2_topic_agents.py`, `long_term/thread_l2.py`, `long_term/l2_debug_viewer.py`, and their tests as prototype/sidecar artifacts rather than the active path. Active L2 remains `long_term/cli.py build-l2-view` and `validate-l2-view`.
- Prototype cleanup details were later consolidated into the active README files. The files were moved under `long_term/archive/prototype_l2_threads/` and `long_term/archive/prototype_memory_ui/`.

### 2026-05-09 - Implement Active L2 Direction View

- Added `long_term/build_l2_view.py` and `long_term/validate_l2_view.py` as active CLI-backed workflows over canonical `share_mem` L1 evidence.
- The builder writes `long_term/l2/l2_view.json`, `l2_index.json`, per-meeting `l2_updates/`, `unlinked_l1_report.json`, and a manifest. It is deterministic in the first version and does not call Gemini.
- The generated Grace L2 view currently has 16 L2 topics, 449 linked L1 objects, and 60 intentionally unlinked or low-signal L1 objects. Validation reports 0 severe issues and 15 manual-review warnings.
- L2 assignment now treats L1 `related_topics` as the primary seed: topic hints are normalized, generic/type-like labels are rejected, aliases are mapped to canonical L2 labels, and content rules refine broad seeds or confirm specific seeds. Expected-assignment regression gates still guard known Grace topic links.
- Active recall now retrieves upward L2 topic context from `long_term/l2/l2_index.json`; current L3 work remains sidecar-only unless a reviewed promotion is materialized.

### 2026-05-08 - Add Append-Only Topic-Tree View

- Added the first `share_mem` topic-tree sidecar/view path: `build_topic_view.py` reads canonical raw L1 from `share_mem/tree.json`, writes per-meeting append-only `topic_updates/<meeting_id>.json`, and replays them into `topic_tree.json` plus `topic_index.json`.
- Topic events and state versions are append-only. Old L1 evidence objects remain unchanged; `current_state` and `timeline_digest` are materialized topic caches.
- The v1 builder performs deterministic candidate search first, then uses the configured Gemini model to choose `assign_existing`, `new_l2`, or `new_l3` within that bounded candidate context. Tests use an injected fake assigner instead of external credentials.
- Topic-tree is still not promoted as the replacement for temporal L2/L3. It is ready for evaluation as an additional view over `share_mem` L1.

### 2026-05-07 - Adopt `share_mem` As L1 Canonical Store

- Changed the canonical L1 direction: new shared L1 memory should live under `share_mem/`, with `share_mem/tree.json` as the source for new L1 recall and future topic-tree work.
- Added the implementation entrypoint `uv run share_mem/build_tree.py --transcript-dir meeting_recording/transcript/grace --mode multi-agent --dataset-profile grace --model gemini-2.5-pro --clean`.
- First implementation scope is storage and L1 retrieval source switching only. Short term and topic-tree are not wired yet.
- The actual Grace multi-agent rebuild still needs to be run and inspected through `share_mem/manifest.json`, per-meeting files, sidecars, and research logs.
- Superseded: treating `long_term/tree.json` as the canonical L1 source for new work.

### 2026-05-07 - Focus Long-Term Codex Forks

- Added this canonical `codex.md` plan for focusing the selected long-term parallel/forked Codex chats.
- Expanded the selected thread details so future Codex chats can recover the reasoning behind the current mainline, the incremental baseline, and the topic-tree open branch.
- Added dynamic update rules so future Codex chats can maintain this file directly instead of only producing handoff text.
- Current canonical direction: multi-agent L1 stays primary; temporal compact L2/L3 stays canonical; topic-tree L2/L3 remains an open branch requiring retrieve/context comparison.
- Next first step: evaluate the topic-tree proposal against current semantic L1 retrieval plus temporal parent-chain expansion before changing schema.
- Superseded: four-room role split and any fork instruction that treats SQL or topic trees as already adopted canonical storage.

### 2026-05-07 - Clarify Topic-Tree L2/L3 Proposal

- Clarified that the proposed new L2/L3 shape is many topic trees: L3 topic roots, L2 subtopic/state nodes, and immutable timestamped L1 evidence objects.
- Clarified why upward retrieval matters: L1 gives evidence, while L2/L3 provide the same-topic explanatory frame, current state, and evolution context.
- Decided that pure topic trees are not enough because they can lose "what was this meeting mainly doing?" context.
- Updated the open branch toward a hybrid design: topic tree for cross-meeting topic evolution, plus meeting timeline/node view for per-meeting direction and ordered flow.
- Current canonical direction remains unchanged for code: temporal compact L2/L3 stays canonical until the hybrid topic-tree design is evaluated and explicitly promoted.

### 2026-05-07 - Separate Canonical And Windows Local State

- Updated terminology across the handoff to use topic-tree consistently for the open branch.
- Split repo canonical state from this Windows device's local worktree state. Current untracked local artifacts are `04_08_bridge_test_results.json`, `test_bridge.py`, and `long_term/grace output/`.
- Marked the partial `long_term/grace output/...0307_multi_agent` run as stale where it reports `argument` and `open_question` as deferred; current repo code and targeted tests include both types in the bounded type-agent loop.
- Targeted checks from this inspection passed: `tests.test_l2_l3_redesign`, `tests.test_l1_quality`, `tests.test_memory_interaction`, and `tests.test_multi_agent_pipeline`.
- Recorded Windows full unittest `WinError 32` temp SQLite cleanup locks as a separate P2 test hygiene follow-up, not a blocker for the P0 topic-tree comparison.
- Next step remains unchanged: write the topic-tree versus temporal parent-chain comparison before changing schema.
