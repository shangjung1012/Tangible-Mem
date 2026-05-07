# Codex Long-Term Handoff

Last updated: 2026-05-07 Asia/Taipei

This file is the canonical handoff state for continuing `long_term/` work across devices and across the selected forked Codex chats. Treat older or out-of-focus Codex sessions as historical evidence, not as equally current instructions. If a forked chat conflicts with this file or the current repo, prefer the current repo plus this file.

Do not commit `.env`, API keys, credential paths, `~/.codex/auth.json`, or raw Codex JSONL histories.

## Long-Term Current State

- Repository state inspected on `main` at `fe8e0a8 Improve multi-agent batch split handling`; local branch was clean before this handoff file was created.
- `long_term/` is the cross-meeting memory module. Canonical storage is still `long_term/tree.json`; L1 objects are produced per meeting, then summarized upward into L2 phase summaries and the L3 project profile.
- The current L1 research mainline is `uv run long_term/cli.py bridge --mode multi-agent`. `full` / `monolithic` and `incremental` remain baselines or references, not the primary development path.
- Multi-agent L1 is a staged prompt pipeline, not autonomous long-lived agents: `prior_context_pack -> context_planner -> segmentation -> repair/coarsening -> boundary refinement -> idea units -> bounded type agents -> grounding -> conflict resolution -> verifier -> reducer -> persist L1 -> relation/activity sidecars`.
- L1 supports six memory object types: `decision`, `todo`, `method_change`, `result`, `open_question`, and `argument`.
- L2/L3 are currently compact temporal summaries, not topic trees. L2 uses `summary`, `changes`, `open_to_next`, and `child_meeting_ids`; L3 uses `core_goal`, `current_phase`, `established_methods`, `long_term_open_questions`, and `child_phase_ids`.
- Recall is centered on semantic L1 retrieval plus recency/importance scoring, optional Recall Gate filtering, parent-chain expansion to the matching L2/L3, and conservative sidecar expansion through memory relations/activity.
- Multi-agent quality, recurrence, relation, and activity metadata live in sidecars such as `l1_quality_index.json`, `memory_relations_index.json`, and `memory_activity_index.json`; the canonical L1 schema remains clean.
- `summarize phase` can read the L1 quality sidecar and treat strong/normal/tentative/weak L1 evidence differently. Legacy L1 without sidecar quality is still allowed.
- Local generated stores and research outputs such as embedding caches, incremental DBs, Grace outputs, and research logs are working artifacts unless explicitly promoted through documentation.

Useful commands:

```bash
uv sync
uv run long_term/cli.py --help
uv run long_term/cli.py bridge --transcript meeting_recording/transcript/grace/0422.txt --mode multi-agent --research-log-dir long_term/research_logs
uv run long_term/cli.py summarize phase --help
uv run long_term/cli.py build-tree --resume --phase-size 4
uv run python -m unittest discover -s tests
```

## Merged Task Board

| Status | Priority | Task | Canonical next step |
| --- | --- | --- | --- |
| active | P0 | Decide whether the L2/L3 topic-tree proposal should replace or complement the current temporal parent chain. | Compare topic trees against the current temporal L2/L3 on retrieve behavior: precision, context continuity, ability to show meeting flow, and migration cost. Do not change schema until this comparison is written down. |
| active | P1 | Validate current multi-agent L1 plus sidecars on real Grace/ICSI meetings. | Run a small repeatable set, inspect `status.json`, `run_summary.json`, `metrics_summary.json`, `l1_quality_index.json`, relation/activity sidecars, and final `tree.json` diffs. |
| active | P1 | Tighten recall behavior around L1 -> L2/L3 parent-chain context. | Check whether retrieved answers get enough high-level context without flooding prompts. Prefer compact L2/L3 plus linked sidecar context before inventing a new retrieval store. |
| active | P2 | Keep multi-agent cost and failure visibility under control. | When a run is slow or interrupted, inspect per-run `status.json` and `run_summary.json` first. Add targeted fixes only where artifacts show a bottleneck. |
| done | P0 | Merge the selected long-term Codex chats into one canonical handoff flow. | Use this `codex.md` as the single entrypoint for future chats. |
| done | P1 | Adopt semantic L1 retrieval with parent-chain expansion. | Treat `long_term/docs/RETRIEVE_IMPLEMENTATION_PLAN.md` as historical implementation context; current code/docs are the source of truth. |
| done | P1 | Adopt compact L2/L3 schema. | Temporal L2/L3 remains canonical unless the topic-tree branch is explicitly promoted. |
| done | P2 | Keep incremental bridge as a reference path. | SQLite issue tables are working state for incremental mode only; do not migrate `tree.json` to SQL just because incremental mode uses SQLite internally. |
| superseded | P0 | Maintain four separate Codex room roles for long-term work. | Replaced by one canonical long-term handoff plus focused thread lineage below. |
| superseded | P2 | Treat forked chats as current independent plans. | Forks must be summarized here before they can steer implementation. |

## Focused Thread Lineage

Only the following selected Codex chats should steer future `long_term/` work. Other local sessions can still be searched privately if needed, but they are not part of the active handoff unless a conclusion is summarized back here.

| Thread / fork | Status | Capsule |
| --- | --- | --- |
| `019df723` - `分析長期架構邏輯` | merged | High-level architecture review concluded: multi-agent is strongest in traceability, bounded scope, deterministic guardrails, and schema compatibility; weak points are cost, run resumption/failure closure, type ambiguity, relation depth, and using rich sidecar signals in L2/L3/recall. Later work addressed several of these through status/run summary and sidecars. |
| `019df88d`, `019df912`, `019dfa5f` - incremental/multi-agent forked work | merged as historical forks | These large forked histories include incremental bridge implementation, run checks, pushes, and long-running multi-agent status checks. Use current repo/docs, not raw fork instructions, for implementation decisions. |
| `019dfc8f` - `評估 L2/L3 主題樹方案` | open branch | Proposed replacing time-based L2/L3 with topic-oriented trees where objects append over time. Not adopted yet. Main unresolved question: can topic trees improve retrieve precision while preserving meeting flow and temporal context better than current L1 retrieval plus temporal parent chain? |

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
- Inspect `long_term/incremental_store.py`, `long_term/gemini_incremental_extractor.py`, `long_term/bridge.py`, and `long_term/dataset_profiles.py` before changing behavior.
- Keep `tree.json` as canonical unless there is a separate storage migration plan with tests and rollback.
- If incremental mode is used for evaluation, compare output quality against multi-agent on the same transcript set and report both accepted L1 objects and rejected/low-confidence candidates.

### `019dfc8f` - Topic-Tree Open Branch

Use this thread as the active design fork to evaluate next.

Proposal:

- Current retrieve starts from an L1 match and brings in the L2/L3 parent from the same temporal phase/project profile.
- The topic-tree idea would add or replace that upward path with topic-oriented thread trees: one meeting's objects can be distributed across multiple topic threads, and future objects append as new timestamped events under the same topic.
- Old L1 objects should remain append-only and evidence-grounded. The dynamic part should be the topic thread's `current_state`, `timeline_digest`, or topic-level summary, not the original L1 evidence object.

Expected benefits:

- Higher retrieve precision for "how did this topic evolve?" questions, because parent context would be same-topic rather than same-time-window.
- Better preservation of evolution: early hypotheses, later changes, abandoned alternatives, and current state can coexist instead of being overwritten by a summary.
- Cleaner global project memory: L3 could become an overview of active topic states rather than one large flattened project summary.
- Stronger answers to "why" questions, because a topic thread can connect decisions, arguments, method changes, results, and open questions across meetings.

Main risks:

- Topic clustering can split one real topic into multiple trees or merge unrelated topics. Either mistake hurts recall more subtly than temporal phases.
- A single meeting's flow can become harder to reconstruct if its objects are scattered across topic trees.
- Append-only topic history can bloat prompts unless it separates raw event history, compact timeline digest, and current state.
- Topic state can duplicate relation/activity sidecars if the responsibilities are not clear.
- Replacing temporal L2/L3 too early would disturb summarize, recall, snapshots, and evaluation without proof.

Evaluation question:

- Compare current retrieval (`semantic L1 -> temporal L2/L3 parent chain -> relation/activity soft expansion`) against a proposed topic path (`semantic L1/topic search -> topic thread -> current state + relevant event timeline`).
- Measure whether topic retrieval improves precision and explanation quality while still preserving meeting progression.
- Treat the first implementation as an additional sidecar/view unless the comparison clearly shows it should replace temporal L2/L3.

## Design Decisions

- `codex.md` is the canonical cross-device handoff; raw Codex JSONL is private backup only.
- Keep `tree.json` as the canonical long-term store. SQLite remains working state for incremental extraction, not the long-term source of truth.
- Keep temporal L2/L3 as canonical until the topic-tree branch is evaluated and explicitly promoted.
- Retrieve should start from L1 because L1 has concrete evidence; L2/L3 are brought in through parent-chain expansion to provide phase/project context.
- Preserve meeting flow by keeping temporal containment available even if topic-oriented views are later added.
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
- If current repo code disagrees with a previous note in this file, inspect the code and update the note instead of carrying both as equal truth.
- If the change is exploratory and no canonical state changed, leave `codex.md` untouched and just report findings.

## Topic-Tree Evaluation Checklist

Before implementing the topic-tree branch as canonical schema, write down the comparison result for these questions:

- Retrieval precision: for topic-evolution questions, does topic-thread expansion return less irrelevant context than temporal L2/L3 parent-chain expansion?
- Meeting continuity: can the system still answer "what happened in this meeting?" after one meeting's L1 objects are distributed across multiple topics?
- Evidence preservation: are old L1 objects still immutable and grounded to their original transcript lines?
- State separation: does the design clearly separate raw events, topic `current_state`, compact `timeline_digest`, and optional topic overview?
- Sidecar boundary: does topic state complement `memory_relations_index.json` / `memory_activity_index.json`, or does it duplicate them?
- Prompt budget: can retrieval include only the latest topic state and a short relevant timeline instead of the full append-only history?
- Migration cost: what code must change in summarize, recall, snapshots, tests, and docs if topic trees replace temporal L2/L3?
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

### 2026-05-07 - Focus Long-Term Codex Forks

- Added this canonical `codex.md` plan for focusing the selected long-term parallel/forked Codex chats.
- Expanded the selected thread details so future Codex chats can recover the reasoning behind the current mainline, the incremental baseline, and the topic-tree open branch.
- Added dynamic update rules so future Codex chats can maintain this file directly instead of only producing handoff text.
- Current canonical direction: multi-agent L1 stays primary; temporal compact L2/L3 stays canonical; topic-tree L2/L3 remains an open branch requiring retrieve/context comparison.
- Next first step: evaluate the topic-tree proposal against current semantic L1 retrieval plus temporal parent-chain expansion before changing schema.
- Superseded: four-room role split and any fork instruction that treats SQL or topic trees as already adopted canonical storage.
