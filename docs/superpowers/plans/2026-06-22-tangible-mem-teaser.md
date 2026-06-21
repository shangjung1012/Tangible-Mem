# Tangible Mem Teaser Figure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the paper teaser with a conceptual Tangible Mem figure that makes the layered memory contribution clear at first glance.

**Architecture:** Add a repo-native HTML/CSS figure source under `doc/taichi/figures`, render it to PNG with Playwright, copy the PNG into the Overleaf `figures/` folder, and update the teaser figure include/caption in `main.tex`. Keep the existing ICSI presentation composite for the walkthrough section.

**Tech Stack:** Static HTML/CSS, Playwright screenshot rendering, LaTeX `acmart` teaser figure.

---

### Task 1: Add Teaser Figure Source

**Files:**
- Create: `doc/taichi/figures/tangible_mem_teaser.html`
- Create after render: `doc/taichi/figures/tangible_mem_teaser.png`

- [ ] **Step 1: Create an HTML/CSS figure source**

Create a single-file HTML figure with:
- A title: `Tangible Mem`
- A subtitle explaining that meeting memory becomes inspectable layered objects.
- A left-to-right flow from meeting transcripts to L1 evidence, L2 topic states, L3 topic families, Memory Observatory, sidecar feedback, and answer context.
- A stacked visual structure that uses height/elevation to make the hierarchy tangible.
- Color roles: L1 blue, L2 purple, L3 amber, sidecar feedback green.

- [ ] **Step 2: Render the PNG**

Run:

```powershell
@'
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(r"C:\Users\yiihsinn\Documents\project_git\virtual-mentor")
html = root / "doc" / "taichi" / "figures" / "tangible_mem_teaser.html"
out = root / "doc" / "taichi" / "figures" / "tangible_mem_teaser.png"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1800, "height": 1050}, device_scale_factor=1)
    page.goto(html.as_uri(), wait_until="networkidle")
    page.screenshot(path=str(out), full_page=True)
    browser.close()
print(out)
'@ | uv run python -
```

Expected: `doc/taichi/figures/tangible_mem_teaser.png` exists and visually shows the layered Tangible Mem workbench.

### Task 2: Update Overleaf Teaser

**Files:**
- Copy to: `C:\Users\yiihsinn\Documents\project_git\taichi-overleaf\figures\tangible_mem_teaser.png`
- Modify: `C:\Users\yiihsinn\Documents\project_git\taichi-overleaf\main.tex`

- [ ] **Step 1: Copy the rendered PNG to Overleaf**

Run:

```powershell
Copy-Item -LiteralPath doc\taichi\figures\tangible_mem_teaser.png `
  -Destination C:\Users\yiihsinn\Documents\project_git\taichi-overleaf\figures\tangible_mem_teaser.png `
  -Force
```

- [ ] **Step 2: Update `main.tex` teaser include and caption**

Change the teaser figure to:

```latex
\begin{teaserfigure}
 \includegraphics[width=\linewidth,height=.62\textheight,keepaspectratio]{figures/tangible_mem_teaser.png}
 \caption{\tool makes long-term research-meeting memory tangible as layered, inspectable objects. Source transcripts are transformed into L1 evidence cards, organized into L2 topic states and L3 topic families, inspected through the Memory Observatory interface, corrected through sidecar feedback, and assembled into evidence-grounded answer context.}
 \Description{A Tangible Mem conceptual teaser showing meeting transcripts becoming L1 evidence cards, L2 topic trays, L3 topic-family shelves, a Memory Observatory inspection surface, sidecar feedback notes, and evidence-grounded answer context.}
 \label{fig:teaser_figure}
\end{teaserfigure}
```

### Task 3: Verify and Push

**Files:**
- Check: Overleaf `main.pdf`
- Commit in both repositories.

- [ ] **Step 1: Compile Overleaf**

Run:

```powershell
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

Expected: build succeeds. Existing citation warnings may remain, but there must be no missing figure error.

- [ ] **Step 2: Render the teaser page preview**

Run:

```powershell
New-Item -ItemType Directory -Force codex_pdf_preview | Out-Null
pdftoppm -f 1 -l 1 -png -r 120 main.pdf codex_pdf_preview\teaser_page
```

Expected: `codex_pdf_preview/teaser_page-01.png` shows the new conceptual Tangible Mem teaser.

- [ ] **Step 3: Clean build artifacts**

Run:

```powershell
$files = @('comment.cut','main.aux','main.bbl','main.blg','main.fdb_latexmk','main.fls','main.log','main.out','main.pdf')
foreach ($f in $files) { if (Test-Path $f) { Remove-Item $f -Force } }
if (Test-Path codex_pdf_preview) { Remove-Item codex_pdf_preview -Recurse -Force }
```

- [ ] **Step 4: Commit and push**

Commit only the teaser-related files in `virtual-mentor`, then commit and push the Overleaf PNG and `main.tex`.
