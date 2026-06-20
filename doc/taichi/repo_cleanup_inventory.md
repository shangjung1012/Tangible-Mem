# Repo Cleanup Inventory For TAICHI Prep

This inventory records the current paper/demo-related working-tree items and how
they should be treated.

## Should Keep For TAICHI Demo

- `memory_observatory/static/app.js`
- `memory_observatory/static/index.html`
- `memory_observatory/static/styles.css`

Reason:

These changes add the `Demo Story` tab and presentation-focused UI elements that
support the Section 5 walkthrough.

- `memory_observatory/static/presentation.html`
- `memory_observatory/static/presentation.css`
- `memory_observatory/static/presentation.js`

Reason:

These files provide a compact capture page for screenshots and paper figures.

- `docs/presentation_diagrams/`

Reason:

These are static diagrams and rendered previews for paper/slides. They should be
reviewed visually before final submission, but they are relevant demo assets.

- `optimization/reports/optimization_v2_decision_catalog_20260615.pdf`
- `optimization/reports/optimization_v2_decision_catalog_20260615.tex`

Reason:

These are implementation-detail references for reviewer questions and appendix
material.

## Experimental But Potentially Useful

- `optimization/long_term_v2/run_grace_l2_l3_ablation.py`
- `tests/test_grace_l2_l3_ablation.py`
- `optimization/reports/grace_l2_l3_ablation_20260614/`

Reason:

These appear to support Grace L2/L3 ablation analysis. Keep only if the ablation
is referenced by the paper, appendix, or future regression work.

## Do Not Use As Evidence

- `optimization/reports/grace_l2_l3_ablation_20260614_speech494618_discarded/`

Reason:

The folder contains `DO_NOT_USE_wrong_project.txt`. It should not be cited in
paper, presentation, or partner handoff. It can be archived or left untracked,
but should not be promoted as a result.

## Clean Documentation Added In This Pass

- `README.md`
- `doc/project_folder_map.md`
- `optimization/README.md`
- `optimization/TODO.md`
- `memory_observatory/README.md`
- `doc/taichi/`

Reason:

These files turn the current system state into an understandable handoff for
TAICHI writing and demo preparation.

## Remaining Cleanup Decisions

- Decide whether the presentation diagrams should be committed in the repo or
  exported into a paper-asset release folder.
- Decide whether Grace ablation code/report is still part of the active story.
- Decide whether discarded report folders should be moved to a local archive or
  ignored.
- Confirm if ICSI `completed29` is the final paper artifact or if a newer final
  completed run should replace it.
