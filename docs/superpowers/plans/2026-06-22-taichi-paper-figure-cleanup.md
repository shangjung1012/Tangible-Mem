# TAICHI Paper Figure Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the remaining TAICHI paper figures from slide-like or incomplete screenshots into concise, paper-ready figures.

**Architecture:** Keep Figure 1 and the Section 3 overview as schematic figures generated from HTML/CSS. Keep Sections 4-5 as UI evidence figures, but crop and compose them so each screenshot has a clear paper role and no empty inspection panel. Sync only final PNG artifacts into the Overleaf repository.

**Tech Stack:** Static HTML/CSS, Playwright screenshot rendering, Python/Pillow image composition, LaTeX compile verification with `latexmk`.

---

### Task 1: Plan And Scope

**Files:**
- Create: `docs/superpowers/plans/2026-06-22-taichi-paper-figure-cleanup.md`

- [ ] **Step 1: Record figure cleanup scope**

Document the intended changes:

- Section 3 overview becomes a concise schematic, not a slide.
- Retrieval Trace becomes a cropped four-panel evidence figure.
- Topic Observatory and Memory Explorer must show selected details, not empty placeholder panels.
- Walkthrough becomes a three-step paper walkthrough, not a presentation board.

- [ ] **Step 2: Verify only relevant figures are in scope**

Run:

```powershell
Select-String -Path C:\Users\yiihsinn\Documents\project_git\taichi-overleaf\main.tex,C:\Users\yiihsinn\Documents\project_git\taichi-overleaf\sections\*.tex -Pattern "\\includegraphics"
```

Expected: the active Tangible Mem figures are the teaser, system overview, retrieval trace, topic/memory explorer pair, and ICSI walkthrough composite.

### Task 2: Redraw Section 3 Overview

**Files:**
- Modify: `doc/taichi/figures/memory_observatory_system_overview.html`
- Regenerate: `doc/taichi/figures/memory_observatory_system_overview.png`

- [ ] **Step 1: Replace slide-like overview with paper schematic**

The figure should show six concise modules:

```text
Input L1 Store -> Topic Surface -> Retrieval Trace -> Observatory Views -> Sidecar Feedback -> Effective Memory
```

Use short labels only. Put explanatory prose in the caption, not in the image.

- [ ] **Step 2: Render PNG with Playwright**

Run:

```powershell
uv run python - <<'PY'
from pathlib import Path
from playwright.sync_api import sync_playwright
root = Path(r"C:\Users\yiihsinn\Documents\project_git\virtual-mentor")
html = root / "doc" / "taichi" / "figures" / "memory_observatory_system_overview.html"
out = root / "doc" / "taichi" / "figures" / "memory_observatory_system_overview.png"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1800, "height": 980}, device_scale_factor=1)
    page.goto(html.as_uri(), wait_until="networkidle")
    page.screenshot(path=str(out), full_page=True)
    browser.close()
PY
```

- [ ] **Step 3: Visually inspect**

Open the PNG and confirm:

- no title/slogan block
- no long paragraph inside the figure
- no clipping
- module labels remain readable after paper scaling

### Task 3: Generate Paper-Ready UI Evidence Figures

**Files:**
- Create: `doc/taichi/figures/build_paper_figures.py`
- Regenerate:
  - `doc/taichi/screenshots/observatory_trace_icsi_focused.png`
  - `doc/taichi/screenshots/observatory_topic_observatory_icsi.png`
  - `doc/taichi/screenshots/observatory_memory_explorer_icsi.png`
  - `doc/taichi/screenshots/observatory_presentation_icsi.png`

- [ ] **Step 1: Build a deterministic composition script**

Create a small Python script that uses Pillow to:

- crop unnecessary browser/sidebar space when appropriate
- add restrained panel labels
- avoid large black title bars
- preserve enough real UI pixels to serve as evidence

- [ ] **Step 2: Rebuild retrieval trace**

Use the existing focused trace screenshot as input, but replace the heavy black panel bars with small paper labels if possible. The output should still show:

- query/plan
- L1 evidence
- L2/L3 context
- formatted prompt context

- [ ] **Step 3: Rebuild topic and memory explorer figures**

If live selected-detail screenshots are unavailable, crop the existing UI screenshots to emphasize the visible populated left/middle panels and reduce blank right panels. Do not fabricate UI content.

- [ ] **Step 4: Rebuild walkthrough composite**

Create a three-step figure using smaller crops:

```text
1. Topic memory before query
2. L1-first retrieval trace
3. Context strategy comparison
```

Each step gets one short label and one real UI crop.

### Task 4: Sync To Overleaf And Verify

**Files:**
- Copy to: `C:\Users\yiihsinn\Documents\project_git\taichi-overleaf\figures\*.png`

- [ ] **Step 1: Pull Overleaf latest**

Run:

```powershell
git -C C:\Users\yiihsinn\Documents\project_git\taichi-overleaf pull --rebase origin main
```

- [ ] **Step 2: Copy regenerated PNGs**

Copy the regenerated PNGs from `virtual-mentor/doc/taichi` into `taichi-overleaf/figures`.

- [ ] **Step 3: Compile**

Run:

```powershell
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

Expected: exit code 0.

- [ ] **Step 4: Render selected pages**

Render pages containing the changed figures with `pdftoppm` and inspect that no figure is clipped or unreadably dense.

### Task 5: Commit And Push

**Files:**
- Stage only figure cleanup files in `virtual-mentor`.
- Stage only regenerated figure PNGs in `taichi-overleaf`.

- [ ] **Step 1: Run docs test**

Run:

```powershell
uv run python -m unittest tests.test_taichi_demo_docs
```

Expected: `OK`.

- [ ] **Step 2: Commit virtual-mentor**

Stage only:

- `docs/superpowers/plans/2026-06-22-taichi-paper-figure-cleanup.md`
- `doc/taichi/figures/memory_observatory_system_overview.html`
- `doc/taichi/figures/memory_observatory_system_overview.png`
- `doc/taichi/figures/build_paper_figures.py`
- regenerated screenshots under `doc/taichi/screenshots/`

- [ ] **Step 3: Commit Overleaf**

Stage only regenerated PNGs under `taichi-overleaf/figures`.

- [ ] **Step 4: Push both repos**

Run:

```powershell
git push origin main
```

in each repo after confirming the branch is ahead only by the new commit.
