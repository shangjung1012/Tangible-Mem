# Memory Observatory Demo Visual QA

Last verified: 2026-06-21

## Scope

This QA pass verifies the ICSI paper/demo path for Memory Observatory. It does
not validate canonical replacement and does not mutate canonical memory
artifacts.

## Health Check

Command:

```powershell
uv run python memory_observatory/demo_health_check.py --dataset icsi
```

Result:

- status: `pass`
- backend: `optimization_v2_artifact`
- fixed demo query: delay-and-sum beamforming / close microphones carryover
- selected L1 seeds: `20`
- selected L2 context: `2` metric count, `3` rendered context rows
- selected L3 navigation: `1`
- prompt context chars: `20311`

## Browser QA

Browser check:

- Started a local FastAPI server on a non-conflicting localhost port.
- Opened `/#demo`.
- Waited for `ICSI demo artifacts are ready`.
- Captured the Demo Story panel with the live health card.
- Used the in-app Browser to switch to Retrieval Trace, run the fixed ICSI
  query, and verify that the trace shows L1 evidence seeds, L2 / child-L2
  evolution context, Parent L3 navigation, and Formatted Prompt Context.

New screenshot:

- `doc/taichi/screenshots/observatory_demo_story_health_icsi.png`

Existing paper-ready focused trace screenshot:

- `doc/taichi/screenshots/observatory_trace_icsi_focused.png`

The focused trace screenshot remains the recommended main-paper trace figure.
The new Demo Story screenshot is a companion proof that the live demo reads the
ICSI optimization-v2 artifact path and passes the readiness check.

## Claim Boundary

The UI can support these claims:

- The demo uses ICSI artifact-backed L1/L2/L3 data.
- Retrieval starts from L1 evidence and then surfaces L2 context and L3
  navigation.
- The current ICSI retrieval diagnostic shows higher expected evidence recall
  than lexical RAG with much lower context size than Full Context.

The UI should not be used to claim:

- generated answers are always better than RAG or Full Context;
- the generated topic hierarchy is always correct;
- optimization v2 has fully replaced canonical runtime defaults.
