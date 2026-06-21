# TAICHI Artifact Index

This file lists the current paper/demo artifacts and how they should be used.

## Primary Demo UI

- Memory Observatory:
  `memory_observatory/`
- Partner handoff guide:
  `doc/taichi/demo_handoff_guide.md`
- Machine-readable readiness manifest:
  `doc/taichi/demo_readiness_manifest.json`
- Start command:

```powershell
uv run uvicorn memory_observatory.main:app --reload
```

Recommended pages for screenshots:

- Overview.
- Demo Story.
- Retrieval Trace.
- Topic Observatory.
- Memory Explorer / object detail.
- Importance Review / sidecar feedback.

## Presentation Capture Assets

- `memory_observatory/static/presentation.html`
- `memory_observatory/static/presentation.css`
- `memory_observatory/static/presentation.js`

Use these for controlled screenshot capture when the live Observatory UI is too
busy for a paper figure.

## Paper Figures And Screenshots

- `doc/taichi/figures/memory_observatory_system_overview.png`
- `doc/taichi/screenshots/observatory_trace_icsi_focused.png`
- `doc/taichi/screenshots/observatory_demo_story_health_icsi.png`
- `doc/taichi/screenshots/observatory_topic_observatory_icsi.png`
- `doc/taichi/screenshots/observatory_memory_explorer_icsi.png`
- `doc/taichi/screenshots/observatory_presentation_icsi.png`

Use `observatory_trace_icsi_focused.png` for the main paper body. It is a
cropped composite of the real ICSI Retrieval Trace and is more readable in a
two-column paper than the full-height trace screenshot. Keep
`observatory_trace_icsi_audio_processing.png` as backup evidence or appendix
material.

Use `observatory_demo_story_health_icsi.png` as demo-readiness evidence or a
presentation backup. It shows the live ICSI artifact-backed health panel plus
the retrieval walkthrough.

## Static Diagrams

- `docs/presentation_diagrams/grace_memory_architecture_diagrams.html`
- `docs/presentation_diagrams/grace_memory_architecture_diagrams.pdf`
- `docs/presentation_diagrams/grace_memory_construction_preview.png`
- `docs/presentation_diagrams/grace_retrieval_flow_preview.png`

Use these as draft figure sources. Regenerate or relabel before final paper
submission if visual style or terminology changes.

## Optimization v2 Reports

Official current Grace artifacts:

- `optimization/runs/grace_v2_latest_20260614`
- `optimization/reports/grace_shadow_qa_grace_v2_latest_20260614`
- `optimization/reports/grace_shadow_answer_quality_grace_v2_latest_20260614`

Official current ICSI artifacts:

- `optimization/runs/icsi_bmr_full_completed29_v2_20260614`
- `optimization/reports/icsi_bmr_full_completed29_eval_pack_revised_20260614`
- `optimization/reports/icsi_bmr_full_completed29_system_comparison_revised_20260614`

Implementation/decision details:

- `optimization/reports/optimization_v2_decision_catalog_20260615.pdf`
- `optimization/reports/optimization_v2_decision_catalog_20260615.tex`
- `doc/taichi/demo_handoff_guide.md`
- `doc/taichi/demo_readiness_manifest.json`
- `doc/taichi/demo_visual_qa.md`

## Retrieval Comparison Numbers

Current ICSI revised no-LLM retrieval/evidence diagnostic:

| Strategy | Expected L1 recall | Avg context tokens | Avg selected L1 |
|---|---:|---:|---:|
| Full context L1 | 1.0 | 575199.0 | 4715.0 |
| RAG lexical top-20 | 0.5583 | 2369.95 | 20.0 |
| Optimization v2 layered | 0.8958 | 7358.35 | 60.0 |

Interpretation:

- Full context is an upper-bound evidence condition, not an efficient interface.
- RAG is compact but loses expected evidence.
- Optimization v2 is the current inspected tradeoff for evidence recall plus
  topic traceability in this diagnostic.
- This is not final generated-answer scoring.

## Do Not Use As Paper Evidence

- `optimization/reports/grace_l2_l3_ablation_20260614_speech494618_discarded/`

Reason:

- Contains `DO_NOT_USE_wrong_project.txt`.

## Missing Or To Be Confirmed

- Final ICSI completed-run root if newer than completed29 exists.
- Final title/conference metadata check in Overleaf `main.tex`.
- Human-auditable answer-quality comparison beyond no-LLM retrieval diagnostics.
- Term/L2/L3 decision audit exports if detailed reviewer appendix is needed.
