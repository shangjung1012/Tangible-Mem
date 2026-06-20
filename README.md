# Virtual Mentor

Virtual Mentor is a meeting-memory QA and inspection system. The current
architecture separates raw evidence, generated topic views, retrieval, and demo
inspection surfaces:

```text
meeting transcripts
-> share_mem canonical L1 evidence
-> long_term canonical generated L2/L3 topic context
-> optimization v2 sidecar L2/L3 experiments
-> app memory router / Memory Observatory
```

`share_mem/` is the canonical L1 evidence store. Raw L1 evidence should not be
edited by hand. Generated topic views and feedback signals should be rebuilt or
written as sidecars.

## Current Delivery Status

- `Memory Observatory` is the main demo and inspection UI for TAICHI-style
  system presentation.
- `optimization/long_term_v2` is the preferred L2/L3 pipeline for new datasets
  such as ICSI. It is evidence-driven, profile-driven, and sidecar-first.
- Canonical `long_term/l2` and `long_term/l3` remain the active legacy Grace
  baseline unless runtime is explicitly switched to `optimization_v2`.
- ICSI L2/L3 work should read effective/filtered L1 roots, not raw archived
  `share_mem` roots.

## Key Documents

- Architecture flow: `doc/l1_l2_update_retrieve_flow.md`
- Folder responsibilities: `doc/project_folder_map.md`
- TAICHI paper/demo planning: `doc/taichi/`
- L1 store: `share_mem/README.md`
- Long-term canonical L2/L3: `long_term/README.md`
- Optimization v2: `optimization/README.md`
- Memory Observatory: `memory_observatory/README.md`
- Current handoff state: `codex.md`

## Setup

```bash
git clone https://github.com/shangjung1012/virtual-mentor.git
cd virtual-mentor
uv sync
```

Create a local `.env` only for credentials and local runtime settings. Do not
commit `.env`.

Common variables:

```text
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=<project-id>
GOOGLE_CLOUD_LOCATION=global
GOOGLE_APPLICATION_CREDENTIALS=<path-to-adc-json>
GEMINI_MODEL=gemini-2.5-pro
GEMINI_PLANNER_MODEL=gemini-2.5-flash
```

## Run The Chat App

```bash
uv run app/main.py
```

## Run The Memory Observatory Demo

```bash
uv run uvicorn memory_observatory.main:app --reload
```

Open:

```text
http://localhost:8000/
```

The Observatory is the recommended surface for showing:

- immutable L1 evidence objects;
- L2 / child-L2 / L3 topic context;
- retrieval traces;
- sidecar-only feedback and importance correction;
- Full Context / RAG / Layered Memory comparison artifacts.

## Build Canonical Grace Memory

Build canonical L1:

```bash
uv run share_mem/build_tree.py --transcript-dir meeting_recording/transcript/grace --output-root share_mem --mode multi-agent --dataset-profile grace --model gemini-2.5-pro --taxonomy v2-memory-roles --include-legacy-type --clean
```

Build and validate canonical L2/L3:

```bash
uv run long_term/cli.py build-l2-view --share-mem-root share_mem --output-root long_term/l2 --mode deterministic --clean
uv run long_term/cli.py validate-l2-view --share-mem-root share_mem --root long_term/l2 --out long_term/l2/validation
uv run long_term/cli.py validate-l3-view --share-mem-root share_mem --l2-root long_term/l2 --l3-root long_term/l3 --out long_term/l3/validation
uv run python long_term/evaluate_retrieval.py --queries long_term/eval/long_term_retrieval_queries.jsonl --out long_term/eval --no-llm --retrieval-mode lexical
```

Do not rebuild canonical artifacts during demo or paper-preparation work unless
the task explicitly asks for canonical regeneration.

## Run Optimization v2

Optimization v2 writes isolated sidecar outputs under `optimization/runs/`.

```bash
uv run python optimization/long_term_v2/build_view.py --share-mem-root share_mem --profile optimization/long_term_v2/profiles/mentor_mentee.yaml --out optimization/runs/grace_v2_latest_local --mode deterministic --clean
uv run python optimization/long_term_v2/validate_view.py --run-root optimization/runs/grace_v2_latest_local
```

For ICSI, use a filtered/effective L1 root:

```bash
uv run python optimization/long_term_v2/build_view.py --share-mem-root memory_outputs/icsi/runs/<run>/share_mem_effective --profile optimization/long_term_v2/profiles/isci_meeting.yaml --out optimization/runs/icsi_v2_latest_local --mode deterministic --clean
uv run python optimization/long_term_v2/validate_view.py --run-root optimization/runs/icsi_v2_latest_local
```

## Runtime Backend Switch

Default runtime uses canonical artifacts. To inspect an exported optimization v2
runtime sidecar:

```powershell
$env:LONG_TERM_BACKEND = "optimization_v2"
$env:OPTIMIZATION_V2_RUN_ROOT = "optimization/runs/<approved-run>"
```

Unset those variables to return to canonical runtime behavior.

## Repository Safety Rules

- Do not manually edit `share_mem/tree.json` or `share_mem/meetings/*`.
- Do not overwrite `long_term/l2` or `long_term/l3` from optimization outputs.
- Keep new dataset outputs under `memory_outputs/` or `optimization/runs/`.
- Treat `optimization v2` as the new-dataset L2/L3 default, not as automatic
  canonical replacement.
- Keep demo artifacts small and documented; do not commit large raw run folders
  unless a release/LFS decision has been made.
