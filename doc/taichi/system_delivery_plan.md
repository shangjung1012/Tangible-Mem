# TAICHI Demo System Delivery Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Memory Observatory stable enough for TAICHI paper demos by fixing demo state, adding a health check, tightening reviewer-facing UI wording, and documenting the exact demo contract.

**Architecture:** This is a delivery hardening pass, not a memory-pipeline rewrite. The work stays in `memory_observatory/`, `tests/`, and `doc/taichi/`; it must not modify canonical `share_mem/`, `long_term/l2`, `long_term/l3`, or optimization-v2 core topic induction. The demo should default to the ICSI artifact-backed dataset, expose an evidence-first trace, and clearly label L3 as navigation context rather than factual evidence.

**Tech Stack:** FastAPI, static HTML/CSS/JS, Python `unittest`, optional Playwright visual QA.

---

## Scope Boundaries

Do not change:

- `share_mem/tree.json`
- `share_mem/meetings/*`
- `long_term/l2/*`
- `long_term/l3/*`
- `optimization/long_term_v2/*`
- ICSI raw L1 extraction outputs

Allowed changes:

- `memory_observatory/main.py`
- `memory_observatory/services/demo_health.py`
- `memory_observatory/static/index.html`
- `memory_observatory/static/app.js`
- `memory_observatory/static/styles.css`
- `memory_observatory/static/presentation.html`
- `memory_observatory/static/presentation.css`
- `memory_observatory/static/presentation.js`
- `memory_observatory/README.md`
- `doc/taichi/*.md`
- `tests/test_memory_observatory.py`
- `tests/test_memory_observatory_static_ui.py`
- `tests/test_memory_observatory_demo_health.py`

Current ICSI demo contract:

- Dataset id: `icsi`
- L1 source: `optimization/reports/icsi_bmr_full_completed29_eval_pack_20260614/source_share_mem`
- L2/L3 runtime source: `optimization/runs/icsi_bmr_full_completed29_v2_20260614/runtime`
- System comparison report: `optimization/reports/icsi_bmr_full_completed29_system_comparison_revised_20260614`
- Demo query:

```text
What context about delay-and-sum beamforming and close microphones should carry over to later audio processing discussions?
```

---

## Task 1: Add A Demo Health Service

**Files:**

- Create: `memory_observatory/services/demo_health.py`
- Modify: `memory_observatory/main.py`
- Test: `tests/test_memory_observatory_demo_health.py`

### Purpose

Add a read-only health check that verifies the demo can load the ICSI dataset, retrieve the fixed demo query, and return the expected high-level components before a live presentation.

### Health Schema

The endpoint should return this shape:

```json
{
  "dataset": "icsi",
  "status": "pass",
  "checks": [
    {"name": "dataset_registered", "status": "pass", "detail": "ICSI dataset is available."},
    {"name": "share_mem_root_exists", "status": "pass", "detail": ".../source_share_mem"},
    {"name": "l2_view_exists", "status": "pass", "detail": ".../runtime/l2/l2_view.json"},
    {"name": "l3_view_exists", "status": "pass", "detail": ".../runtime/l3/l3_view.json"},
    {"name": "demo_trace_has_l1", "status": "pass", "detail": "selected_l1_count=..."},
    {"name": "demo_trace_has_l2", "status": "pass", "detail": "selected_l2_count=..."},
    {"name": "demo_trace_has_prompt", "status": "pass", "detail": "formatted_context_chars=..."}
  ],
  "demo_query": "What context about delay-and-sum beamforming and close microphones should carry over to later audio processing discussions?",
  "resolved_backend": "optimization_v2_artifact",
  "fallback_reason": ""
}
```

Status rules:

- `pass`: all checks pass.
- `warn`: static artifacts exist but trace lacks optional L3 navigation.
- `fail`: dataset missing, L1 root missing, L2/L3 runtime missing, trace errors, or trace returns no L1 evidence.

### Implementation Steps

- [x] **Step 1: Write failing tests for healthy fixture**

Add `tests/test_memory_observatory_demo_health.py`:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from memory_observatory.main import create_app
from tests.test_memory_observatory import _fixture_repo, _fixture_icsi_dataset


class MemoryObservatoryDemoHealthTests(unittest.TestCase):
    def test_demo_health_passes_for_icsi_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture_repo(root)
            _fixture_icsi_dataset(root)
            client = TestClient(create_app(root))

            response = client.get("/api/demo/health?dataset=icsi")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["dataset"], "icsi")
            self.assertIn(payload["status"], {"pass", "warn"})
            names = {item["name"] for item in payload["checks"]}
            self.assertIn("dataset_registered", names)
            self.assertIn("share_mem_root_exists", names)
            self.assertIn("l2_view_exists", names)
            self.assertIn("l3_view_exists", names)
            self.assertIn("demo_trace_has_l1", names)
            self.assertIn("demo_trace_has_l2", names)
            self.assertIn("demo_trace_has_prompt", names)

    def test_demo_health_fails_for_missing_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture_repo(root)
            client = TestClient(create_app(root))

            response = client.get("/api/demo/health?dataset=unknown")

            self.assertEqual(response.status_code, 404)
```

- [x] **Step 2: Run tests and verify failure**

Run:

```powershell
uv run python -m unittest tests.test_memory_observatory_demo_health
```

Expected before implementation:

```text
FAILED (failures=1)
404 Not Found for /api/demo/health?dataset=icsi
```

- [x] **Step 3: Implement `demo_health.py`**

Create `memory_observatory/services/demo_health.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .data_loader import ObservatoryDataLoader
from .datasets import resolve_dataset
from .retrieval_trace import RetrievalTraceService

DEMO_QUERY = "What context about delay-and-sum beamforming and close microphones should carry over to later audio processing discussions?"


@dataclass
class DemoCheck:
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def _check_path(name: str, path: Path) -> DemoCheck:
    if path.exists():
        return DemoCheck(name, "pass", str(path))
    return DemoCheck(name, "fail", f"missing: {path}")


def build_demo_health(repo_root: Path | str, dataset_id: str = "icsi") -> dict[str, Any]:
    root = Path(repo_root)
    dataset = resolve_dataset(root, dataset_id)
    loader = ObservatoryDataLoader(root, dataset_id=dataset.dataset_id)
    checks: list[DemoCheck] = [
        DemoCheck("dataset_registered", "pass", f"{dataset.dataset_id}: {dataset.label}"),
        _check_path("share_mem_root_exists", loader.share_mem_root),
        _check_path("l2_view_exists", loader.l2_root / "l2_view.json"),
        _check_path("l3_view_exists", loader.l3_root / "l3_view.json"),
    ]

    if any(item.status == "fail" for item in checks):
        return {
            "dataset": dataset.dataset_id,
            "status": "fail",
            "checks": [item.as_dict() for item in checks],
            "demo_query": DEMO_QUERY,
            "resolved_backend": "optimization_v2_artifact" if dataset.dataset_id == "icsi" else "canonical",
            "fallback_reason": "required artifact missing",
        }

    try:
        trace = RetrievalTraceService(root, dataset_id=dataset.dataset_id).run_trace(
            query=DEMO_QUERY,
            retrieval_mode="lexical",
            no_llm=True,
            include_debug=False,
            budget_profile="observatory_paper_trace",
            max_context_chars=0,
        )
    except Exception as exc:
        checks.append(DemoCheck("demo_trace_runs", "fail", repr(exc)))
        return {
            "dataset": dataset.dataset_id,
            "status": "fail",
            "checks": [item.as_dict() for item in checks],
            "demo_query": DEMO_QUERY,
            "resolved_backend": "optimization_v2_artifact" if dataset.dataset_id == "icsi" else "canonical",
            "fallback_reason": "trace execution failed",
        }

    plan = trace.get("plan", {}) if isinstance(trace.get("plan"), dict) else {}
    l1_count = int(plan.get("selected_l1_count", len(trace.get("l1_evidence_seeds", []) or [])) or 0)
    l2_count = int(plan.get("selected_l2_count", len(trace.get("l2_context", []) or [])) or 0)
    prompt_text = str(trace.get("formatted_prompt_context") or "")
    l3_count = int(plan.get("selected_l3_count", len(trace.get("l3_navigation", []) or [])) or 0)
    checks.extend(
        [
            DemoCheck("demo_trace_has_l1", "pass" if l1_count > 0 else "fail", f"selected_l1_count={l1_count}"),
            DemoCheck("demo_trace_has_l2", "pass" if l2_count > 0 else "fail", f"selected_l2_count={l2_count}"),
            DemoCheck("demo_trace_has_prompt", "pass" if len(prompt_text) > 0 else "fail", f"formatted_context_chars={len(prompt_text)}"),
            DemoCheck("demo_trace_has_l3_navigation", "pass" if l3_count > 0 else "warn", f"selected_l3_count={l3_count}"),
        ]
    )

    statuses = {item.status for item in checks}
    status = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"
    return {
        "dataset": dataset.dataset_id,
        "status": status,
        "checks": [item.as_dict() for item in checks],
        "demo_query": DEMO_QUERY,
        "resolved_backend": "optimization_v2_artifact" if dataset.dataset_id == "icsi" else "canonical",
        "fallback_reason": "" if status != "fail" else "required demo check failed",
    }
```

- [x] **Step 4: Wire endpoint in `main.py`**

Modify `memory_observatory/main.py`:

```python
from .services.demo_health import build_demo_health
```

Add after `/api/overview`:

```python
    @app.get("/api/demo/health")
    def api_demo_health(dataset: str = "icsi") -> dict[str, Any]:
        dataset_id = dataset_or_404(dataset)
        return build_demo_health(root, dataset_id=dataset_id)
```

- [x] **Step 5: Verify test passes**

Run:

```powershell
uv run python -m unittest tests.test_memory_observatory_demo_health
```

Expected:

```text
OK
```

---

## Task 2: Add A Demo Health Panel To The UI

**Files:**

- Modify: `memory_observatory/static/index.html`
- Modify: `memory_observatory/static/app.js`
- Modify: `memory_observatory/static/styles.css`
- Test: `tests/test_memory_observatory_static_ui.py`

### Purpose

The live demo should show a compact status panel that confirms the selected corpus, backend, and trace readiness. This prevents silent failures during a talk and gives partners a quick way to know whether they are demoing the intended ICSI state.

### Implementation Steps

- [x] **Step 1: Add static UI tests**

Extend `MemoryObservatoryStaticUiTests`:

```python
    def test_demo_story_has_health_panel(self) -> None:
        html = (REPO_ROOT / "memory_observatory" / "static" / "index.html").read_text(encoding="utf-8")
        js = (REPO_ROOT / "memory_observatory" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("demoHealth", html)
        self.assertIn("/api/demo/health", js)
        self.assertIn("renderDemoHealth", js)
        self.assertIn("resolved backend", js.lower())
        self.assertIn("fallback reason", js.lower())
```

- [x] **Step 2: Run test and verify failure**

Run:

```powershell
uv run python -m unittest tests.test_memory_observatory_static_ui.MemoryObservatoryStaticUiTests.test_demo_story_has_health_panel
```

Expected:

```text
FAILED
```

- [x] **Step 3: Add health panel markup**

In `memory_observatory/static/index.html`, inside `<section id="demo" class="tab">`, insert after `.demo-story-header`:

```html
        <div id="demoHealth" class="demo-health loading">Checking demo health...</div>
```

- [x] **Step 4: Add renderer in `app.js`**

Add:

```javascript
function renderDemoHealth(data) {
  const status = data.status || "unknown";
  const checks = data.checks || [];
  return el("div", { class: `demo-health-card ${status}` }, [
    el("div", { class: "demo-card-top" }, [
      tag(`demo health: ${status}`, status === "pass" ? "feedback" : status === "warn" ? "warn" : "danger"),
      tag(`dataset: ${data.dataset || selectedDataset}`, "l1"),
      tag(`resolved backend: ${data.resolved_backend || "unknown"}`, "l2"),
    ]),
    data.fallback_reason ? el("p", { class: "muted", text: `fallback reason: ${data.fallback_reason}` }) : null,
    el("div", { class: "health-check-grid" }, checks.map((item) =>
      el("div", { class: `health-check ${item.status}` }, [
        el("strong", { text: item.name }),
        el("span", { text: item.status }),
        el("p", { text: item.detail || "" }),
      ])
    )),
  ]);
}
```

In `loadDemoStory()`, call:

```javascript
  const health = await api(`/api/demo/health?dataset=${selectedDataset}`).catch((error) => ({
    dataset: selectedDataset,
    status: "fail",
    checks: [{ name: "demo_health_endpoint", status: "fail", detail: String(error) }],
    resolved_backend: "unknown",
    fallback_reason: "health endpoint failed",
  }));
  $("#demoHealth").replaceChildren(renderDemoHealth(health));
```

- [x] **Step 5: Add styles**

In `memory_observatory/static/styles.css`:

```css
.demo-health-card {
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 8px;
  padding: 12px;
  margin: 16px 0;
}

.demo-health-card.pass { border-color: #0f766e; }
.demo-health-card.warn { border-color: #b45309; }
.demo-health-card.fail { border-color: #b91c1c; }

.health-check-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 8px;
}

.health-check {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  min-width: 0;
}

.health-check span {
  display: inline-block;
  margin-left: 6px;
  font-size: 12px;
  text-transform: uppercase;
}

.health-check p {
  margin: 4px 0 0;
  overflow-wrap: anywhere;
  color: var(--muted);
}
```

- [x] **Step 6: Verify static UI test passes**

Run:

```powershell
uv run python -m unittest tests.test_memory_observatory_static_ui.MemoryObservatoryStaticUiTests.test_demo_story_has_health_panel
```

Expected:

```text
OK
```

---

## Task 3: Tighten Reviewer-Facing Wording

**Files:**

- Modify: `memory_observatory/static/index.html`
- Modify: `memory_observatory/static/app.js`
- Modify: `memory_observatory/static/presentation.html`
- Modify: `memory_observatory/static/presentation.js`
- Test: `tests/test_memory_observatory_static_ui.py`

### Purpose

Make the UI wording match the TAICHI paper claim: the system is an inspectable memory surface, not a proof that generated answers always outperform baselines.

### Required Wording Rules

Use these terms:

- `L1 evidence seeds`
- `L2 topic context`
- `L3 navigation context`
- `Formatted prompt context`
- `Sidecar correction`
- `Navigation context only; factual claims remain grounded in L1 evidence.`

Avoid these terms in visible demo copy:

- `budget pass`
- `planner model gemini`
- `short-term memory`
- `answer superiority`
- `SOTA`
- `topic hierarchy is correct`

### Implementation Steps

- [x] **Step 1: Add static wording tests**

Extend `tests/test_memory_observatory_static_ui.py`:

```python
    def test_taichi_demo_wording_is_conservative(self) -> None:
        html = (REPO_ROOT / "memory_observatory" / "static" / "index.html").read_text(encoding="utf-8")
        js = (REPO_ROOT / "memory_observatory" / "static" / "app.js").read_text(encoding="utf-8")
        presentation = (REPO_ROOT / "memory_observatory" / "static" / "presentation.html").read_text(encoding="utf-8")

        combined = "\n".join([html, js, presentation])
        self.assertIn("L1 evidence seeds", combined)
        self.assertIn("L2 topic context", combined)
        self.assertIn("L3 navigation", combined)
        self.assertIn("Formatted prompt context", combined)
        self.assertIn("sidecar", combined.lower())
        self.assertIn("Navigation context", combined)
        self.assertNotIn("SOTA", combined)
        self.assertNotIn("answer superiority", combined.lower())
        self.assertNotIn("short-term memory", combined.lower())
```

- [x] **Step 2: Run test and record current failures**

Run:

```powershell
uv run python -m unittest tests.test_memory_observatory_static_ui.MemoryObservatoryStaticUiTests.test_taichi_demo_wording_is_conservative
```

Expected:

```text
FAILED
```

- [x] **Step 3: Update visible UI copy**

Replace confusing demo text with:

```text
L3 navigation context orients the user inside a topic family. It is not standalone factual evidence; factual claims remain grounded in L1 evidence cards.
```

For comparison text, use:

```text
Layered Memory is designed for inspectability: it starts from L1 evidence, adds L2 topic context, and exposes L3 navigation. It does not claim that every final answer is better than every baseline.
```

For budget/debug display, keep technical details behind `details` or debug panels and label them:

```text
Technical retrieval metadata
```

- [x] **Step 4: Verify wording tests pass**

Run:

```powershell
uv run python -m unittest tests.test_memory_observatory_static_ui
```

Expected:

```text
OK
```

---

## Task 4: Add Demo Smoke CLI

**Files:**

- Create: `memory_observatory/demo_health_check.py`
- Test: `tests/test_memory_observatory_demo_health.py`

### Purpose

Allow a presenter to run one command before a talk:

```powershell
uv run python memory_observatory/demo_health_check.py --dataset icsi
```

The command should exit `0` for `pass` or `warn`, and exit `1` for `fail`.

### Implementation Steps

- [x] **Step 1: Add CLI test**

In `tests/test_memory_observatory_demo_health.py`, add:

```python
    def test_demo_health_cli_exits_zero_for_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture_repo(root)
            _fixture_icsi_dataset(root)
            from memory_observatory.demo_health_check import run_cli

            code = run_cli(["--repo-root", str(root), "--dataset", "icsi"])

            self.assertEqual(code, 0)
```

- [x] **Step 2: Implement CLI**

Create `memory_observatory/demo_health_check.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from memory_observatory.services.data_loader import REPO_ROOT
from memory_observatory.services.demo_health import build_demo_health


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Memory Observatory demo readiness.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--dataset", default="icsi")
    args = parser.parse_args(argv)
    result = build_demo_health(Path(args.repo_root), dataset_id=args.dataset)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
```

- [x] **Step 3: Verify CLI test**

Run:

```powershell
uv run python -m unittest tests.test_memory_observatory_demo_health
```

Expected:

```text
OK
```

- [x] **Step 4: Run real repo CLI**

Run:

```powershell
uv run python memory_observatory/demo_health_check.py --dataset icsi
```

Expected:

```text
"status": "pass"
```

If status is `warn`, inspect which optional L3 check warned. If status is `fail`, stop and fix the missing artifact before demo.

---

## Task 5: Browser Visual QA For Demo Pages

**Files:**

- Create: `doc/taichi/demo_visual_qa.md`
- No source code changes unless visual QA finds a concrete bug.

### Purpose

Verify the live app behaves like the screenshots and paper story.

### Steps

- [x] **Step 1: Start server**

Run:

```powershell
uv run uvicorn memory_observatory.main:app --host 127.0.0.1 --port 8765
```

Expected:

```text
Uvicorn running on http://127.0.0.1:8765
```

- [x] **Step 2: Open pages**

Use Browser or Playwright to inspect:

```text
http://127.0.0.1:8765/
http://127.0.0.1:8765/static/presentation.html
```

- [x] **Step 3: Record QA results**

Create `doc/taichi/demo_visual_qa.md`:

```markdown
# TAICHI Demo Visual QA

Date: YYYY-MM-DD

## Environment

- Server: `uv run uvicorn memory_observatory.main:app --host 127.0.0.1 --port 8765`
- Dataset: ICSI
- Demo query: `What context about delay-and-sum beamforming and close microphones should carry over to later audio processing discussions?`

## Checks

- [ ] Overview loads with ICSI selected.
- [x] Demo Story shows topic memory before query.
- [x] Demo health panel is pass or warn with no missing core artifacts.
- [x] Retrieval Trace returns L1 evidence seeds.
- [x] Retrieval Trace returns L2 topic context.
- [x] L3 is labeled as navigation context.
- [x] Formatted prompt context is visible.
- [ ] Memory Explorer opens an ICSI L1 object.
- [ ] Topic Observatory opens an audio-related topic.
- [ ] Presentation page is readable at desktop width.

## Notes

- Critical issues:
- Non-critical visual issues:
- Screenshots captured:
```

- [x] **Step 4: Stop server**

Stop the uvicorn process after QA.

---

## Task 6: Documentation Update

**Files:**

- Modify: `memory_observatory/README.md`
- Modify: `doc/taichi/artifact_index.md`
- Modify: `doc/taichi/readiness_checklist.md`

### Purpose

Make the repo self-explanatory for partners who need to run the TAICHI demo without knowing the history of Grace, ICSI, canonical artifacts, or optimization v2.

### Required README Additions

Add a section:

```markdown
## TAICHI Demo Health Check

Before a live demo:

```powershell
uv run python memory_observatory/demo_health_check.py --dataset icsi
```

Expected status:

- `pass`: ready for the TAICHI demo.
- `warn`: usable, but inspect warnings.
- `fail`: do not demo until the missing artifact or trace failure is fixed.

The demo uses ICSI by default and reads optimization-v2 sidecar artifacts. It
does not rewrite canonical `share_mem/`, `long_term/l2`, or `long_term/l3`.
```

Update `doc/taichi/readiness_checklist.md`:

```markdown
- [x] Demo health CLI returns pass for ICSI.
- [x] Browser visual QA recorded in `doc/taichi/demo_visual_qa.md`.
- [x] Partner can run the demo from README without asking which dataset to use.
```

### Verification

Run:

```powershell
uv run python -m unittest tests.test_memory_observatory tests.test_memory_observatory_static_ui tests.test_memory_observatory_demo_health
```

Expected:

```text
OK
```

---

## Task 7: Final Verification And Commit

### Commands

Run:

```powershell
uv run python -m unittest tests.test_memory_observatory tests.test_memory_observatory_static_ui tests.test_memory_observatory_demo_health
uv run python memory_observatory/demo_health_check.py --dataset icsi
git status --short --branch
```

Expected:

```text
OK
"status": "pass"
## main...origin/main
```

If `demo_health_check.py` returns `warn`, commit only if the warning is optional L3 navigation and the UI still displays L1 evidence plus L2 topic context. If it returns `fail`, do not commit until fixed.

### Commit

```powershell
git add memory_observatory tests doc/taichi
git commit -m "Harden TAICHI Memory Observatory demo"
git push origin main
```

---

## Acceptance Criteria

The system delivery pass is complete when:

- ICSI remains the default UI dataset.
- `/api/demo/health?dataset=icsi` exists.
- `uv run python memory_observatory/demo_health_check.py --dataset icsi` returns `pass` or an explicitly documented non-blocking `warn`.
- Demo Story shows health status and the fixed ICSI query.
- Retrieval Trace wording distinguishes L1 evidence, L2 topic context, and L3 navigation.
- L3 is never presented as standalone evidence.
- Demo Story and presentation page use conservative claims.
- Static UI tests pass.
- API smoke tests pass.
- Browser visual QA is recorded.
- No canonical `share_mem/`, `long_term/l2`, or `long_term/l3` files are modified.

## Non-Goals

- Do not rebuild ICSI L1.
- Do not rebuild Grace L1.
- Do not tune optimization-v2 topic induction.
- Do not claim generated-answer superiority.
- Do not implement canonical replacement.
- Do not add a new evaluation benchmark in this pass.
