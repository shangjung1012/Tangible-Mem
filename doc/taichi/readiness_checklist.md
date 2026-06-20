# TAICHI Readiness Checklist

This checklist is for preparing the repository and demo system before writing or
submitting the TAICHI paper.

## P0: Required Before Writing Final System Sections

- [x] Clean top-level README so it explains canonical, optimization v2, and demo
  boundaries.
- [x] Clean folder map so canonical artifacts, optimization outputs, and demo
  assets are separated.
- [x] Create TAICHI paper workspace under `doc/taichi/`.
- [x] Identify official current Grace and ICSI artifacts.
- [x] Mark discarded/wrong-project report as not usable.
- [ ] Confirm whether `completed29` is still the final ICSI paper artifact or
  whether a newer completed run should replace it.
- [ ] Capture paper-ready screenshots from Memory Observatory.
- [ ] Verify Demo Story page visually in browser.
- [ ] Decide whether presentation capture assets should be committed as official
  paper/demo assets.

## P1: Required Before Strong Evaluation Claims

- [ ] Build a small human-auditable answer-quality set for ICSI.
- [ ] Run answer-quality comparison only if API cost is acceptable.
- [ ] Add term decision audit for L2 phrase filtering/scoring explanation.
- [ ] Add L2 assignment audit for assign/unlink/review-only explanation.
- [ ] Add L3 split audit for parent promotion and child-label generation.
- [ ] Refresh TAICHI artifact index after any new Grace/ICSI run.

## P2: Required Before Canonical Replacement

- [ ] Export an approved optimization v2 runtime view.
- [ ] Run shadow-mode QA against canonical.
- [ ] Confirm fallback behavior when v2 runtime export is missing.
- [ ] Get explicit approval before replacing or archiving canonical runtime
  defaults.
- [ ] Keep `share_mem/tree.json` and raw L1 evidence immutable.

## Current Go / No-Go

Go:

- Use Memory Observatory for TAICHI system demonstration.
- Use optimization v2 as the new-dataset L2/L3 pipeline in discussion.
- Use ICSI no-LLM retrieval diagnostic as preliminary technical validation.

No-go:

- Do not claim canonical replacement.
- Do not claim final user-study results.
- Do not use discarded/wrong-project reports.
- Do not claim generated-answer superiority without answer-quality scoring.
