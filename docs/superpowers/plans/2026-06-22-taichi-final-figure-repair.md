# TAICHI Final Figure Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the TAICHI paper figures visually distinct, aligned, readable, and paper-appropriate.

**Architecture:** Figure 1 becomes a contribution-level concept figure, Figure 2 remains the system overview, Figure 5 becomes a readable walkthrough storyboard. Existing UI screenshots remain evidence figures, but generated composites must be validated in both PNG and compiled PDF form.

**Tech Stack:** Static HTML/CSS figure sources, Playwright screenshot rendering, LaTeX/Overleaf PDF compile checks.

---

### Task 1: Redraw Figure 1 As Concept Figure

**Files:**
- Modify: `doc/taichi/figures/tangible_mem_teaser.html`
- Generated: `doc/taichi/figures/tangible_mem_teaser.png`

- [ ] **Step 1: Replace the current pipeline-like teaser with three aligned zones**

Use three equal-width regions:
`Opaque memory` -> `Tangible memory layers` -> `Human steering`.

The middle region must emphasize L1/L2/L3 as stacked inspectable layers, not a left-to-right processing pipeline. The right region must show trace and sidecar correction as human steering actions.

- [ ] **Step 2: Render the PNG**

Run:
`uv run python doc/taichi/figures/render_tangible_mem_teaser.py` if available, otherwise render the HTML with Playwright to `doc/taichi/figures/tangible_mem_teaser.png`.

- [ ] **Step 3: Inspect the PNG**

Check that all major cards share a grid, arrows connect to card centers, no labels overlap, and Figure 1 no longer duplicates Figure 2.

### Task 2: Redraw Figure 5 As Walkthrough Storyboard

**Files:**
- Modify: `doc/taichi/figures/build_paper_figures.py`
- Generated: `doc/taichi/screenshots/observatory_presentation_icsi.png`

- [ ] **Step 1: Replace the screenshot-heavy composite with a four-step storyboard**

Use abstract cards rather than tiny UI screenshots:
`Question` -> `L1 evidence seeds` -> `L2/L3 context` -> `Inspectable prompt + sidecar correction`.

- [ ] **Step 2: Keep only short labels**

Each panel should use 2-4 short lines. Long explanation belongs in the caption, not the figure.

- [ ] **Step 3: Render and inspect**

Run `uv run python doc/taichi/figures/build_paper_figures.py` and inspect the output PNG. Verify it remains readable when scaled to full page width.

### Task 3: Full Figure Visual QA

**Files:**
- Generated: `doc/taichi/figures/*.png`
- Generated: `doc/taichi/screenshots/*.png`
- Overleaf copy: `C:/Users/yiihsinn/Documents/project_git/taichi-overleaf/figures/*.png`

- [ ] **Step 1: Inspect Figure 1, Figure 2, Figure 3, Figure 4, Figure 5 PNGs**

Reject the output if there is any obvious misalignment, clipped text, overlapping elements, or slide-like explanatory blocks.

- [ ] **Step 2: Sync images to Overleaf**

Copy the updated PNG files into `C:/Users/yiihsinn/Documents/project_git/taichi-overleaf/figures/`.

- [ ] **Step 3: Compile and render PDF pages**

Run `latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex`, then render pages containing the figures with `pdftoppm`.

- [ ] **Step 4: Inspect compiled PDF pages**

Check actual paper layout, not just source PNGs. Ensure Figure 1 and Figure 2 are visually distinct, and Figure 5 is readable.

### Task 4: Scoped Commit And Push

**Files:**
- Stage only figure sources, generated figure PNGs, and this plan.

- [ ] **Step 1: Run verification**

Run:
`uv run python -m py_compile doc/taichi/figures/build_paper_figures.py`
`uv run python -m unittest tests.test_taichi_demo_docs`

- [ ] **Step 2: Commit and push virtual-mentor**

Commit scoped changes only. Do not stage unrelated `paper/lit` or Google sync files.

- [ ] **Step 3: Commit and push Overleaf**

Commit only updated figure PNGs.
