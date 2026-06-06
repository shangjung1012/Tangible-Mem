# Memory Output Root Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a clean output-root strategy so Grace, ICSI, and future datasets write L1/L2/L3 trees into explicit run folders instead of mixing generated artifacts into canonical locations.

**Architecture:** Keep immutable/canonical sources separate from generated experiment outputs. Each dataset run gets one self-contained run root containing raw L1, effective/filtered L1, optimization L2/L3, validation, logs, reports, and hashes. Existing canonical `share_mem/`, `long_term/l2`, and `long_term/l3` are not overwritten unless a later explicit promotion command is used.

**Tech Stack:** Python CLI scripts, PowerShell commands, JSON sidecars, existing `share_mem` and `optimization/long_term_v2` builders.

---

## Current Verified State

- `share_mem/tree.json`, `share_mem/meetings/*`, `share_mem/l1_index.json`, `share_mem/manifest.json`, `long_term/l2/*`, and `long_term/l3/*` currently show no git diff.
- ICSI probe outputs are under `share_mem_experiments/...` and `optimization/runs/...`.
- Tooling code has uncommitted changes, but canonical Grace generated artifacts have not been overwritten.

## Target Layout

```text
memory_outputs/
  grace/
    runs/
      grace_l1_<timestamp>/
      grace_l2_l3_<timestamp>/
      grace_full_<timestamp>/
  icsi/
    runs/
      bmr_first360_batch01_<timestamp>/
      bmr_first360_batch02_<timestamp>/
      bmr_full_batch01_<timestamp>/
  synthetic/
    runs/
      synthetic_longmeet_<timestamp>/
  promotion_candidates/
    grace_<timestamp>/
    icsi_<timestamp>/
```

Each run root should contain:

```text
run_manifest.json
source_snapshot/
share_mem_raw/
share_mem_effective/
l2_l3/
validation/
reports/
api_calls/
logs/
hashes/
```

## Task 1: Add A Run-Root Resolver

**Files:**
- Create: `optimization/output_roots.py`
- Test: `tests/test_memory_output_roots.py`

- [ ] **Step 1: Write tests for dataset-safe run roots**

```python
from pathlib import Path

from optimization.output_roots import resolve_memory_run_root


def test_resolve_icsi_run_root_stays_under_memory_outputs(tmp_path):
    root = resolve_memory_run_root(
        base_root=tmp_path / "memory_outputs",
        dataset="icsi",
        run_kind="bmr_first360",
        run_id="batch01_20260605",
    )
    assert root == tmp_path / "memory_outputs" / "icsi" / "runs" / "bmr_first360_batch01_20260605"


def test_reject_canonical_output_paths(tmp_path):
    try:
        resolve_memory_run_root(
            base_root=Path("share_mem"),
            dataset="grace",
            run_kind="l1",
            run_id="bad",
        )
    except ValueError as exc:
        assert "canonical" in str(exc).lower()
    else:
        raise AssertionError("expected canonical path rejection")
```

- [ ] **Step 2: Implement resolver**

```python
from __future__ import annotations

import re
from pathlib import Path


CANONICAL_ROOT_NAMES = {"share_mem", "long_term"}


def _slug(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    clean = clean.strip("._-")
    if not clean:
        raise ValueError("run path component cannot be empty")
    return clean


def resolve_memory_run_root(
    *,
    base_root: Path | str,
    dataset: str,
    run_kind: str,
    run_id: str,
) -> Path:
    base = Path(base_root)
    if base.name in CANONICAL_ROOT_NAMES:
        raise ValueError(f"Refusing canonical output root: {base}")
    return base / _slug(dataset) / "runs" / f"{_slug(run_kind)}_{_slug(run_id)}"
```

- [ ] **Step 3: Run tests**

```powershell
uv run python -m unittest tests.test_memory_output_roots
```

Expected: tests pass.

## Task 2: Add Run Manifest And Hash Writer

**Files:**
- Create: `optimization/run_manifest.py`
- Test: `tests/test_memory_output_roots.py`

- [ ] **Step 1: Add manifest test**

```python
import json

from optimization.run_manifest import write_run_manifest


def test_write_run_manifest_records_source_hashes(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("hello\n", encoding="utf-8")
    manifest = write_run_manifest(
        run_root=tmp_path / "run",
        dataset="icsi",
        run_kind="bmr_first360",
        source_paths=[source],
        config={"line_limit": 360},
    )
    loaded = json.loads((tmp_path / "run" / "run_manifest.json").read_text(encoding="utf-8"))
    assert loaded["dataset"] == "icsi"
    assert loaded["config"]["line_limit"] == 360
    assert loaded["source_hashes"][str(source.resolve())]
    assert manifest == loaded
```

- [ ] **Step 2: Implement manifest writer**

```python
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_run_manifest(
    *,
    run_root: Path | str,
    dataset: str,
    run_kind: str,
    source_paths: list[Path],
    config: dict[str, Any],
) -> dict[str, Any]:
    root = Path(run_root)
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset,
        "run_kind": run_kind,
        "config": config,
        "source_hashes": {str(path.resolve()): _sha256(path) for path in source_paths if path.exists()},
    }
    (root / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
```

- [ ] **Step 3: Run tests**

```powershell
uv run python -m unittest tests.test_memory_output_roots
```

Expected: tests pass.

## Task 3: Update ICSI Batch Runner To Support Unified Output Base

**Files:**
- Modify: `share_mem/run_icsi_batch.py`
- Test: `tests/test_icsi_batch_orchestrator.py`

- [ ] **Step 1: Add CLI support**

Add optional args:

```python
parser.add_argument("--output-base", default="", help="Base folder for dataset run outputs.")
parser.add_argument("--run-id", default="", help="Stable run id used with --output-base.")
```

If `--output-root` is provided, keep current behavior. If omitted and `--output-base` is provided, resolve:

```text
<output-base>/icsi/runs/<run-kind>_<run-id>
```

- [ ] **Step 2: Keep existing sidecar shape**

The resolved run root should still contain:

```text
share_mem/
filtered_share_mem/
final_validation/
batch_status.json
```

- [ ] **Step 3: Add regression checks**

Ensure tests verify:

- canonical `share_mem/` is rejected as output root.
- `filtered_share_mem/manifest.json` is written.
- `batch_status.json` points to the resolved run root.

- [ ] **Step 4: Run targeted tests**

```powershell
uv run python -m unittest tests.test_icsi_batch_orchestrator tests.test_memory_output_roots
```

Expected: tests pass.

## Task 4: Add Grace Rebuild Command Wrapper

**Files:**
- Create: `optimization/run_grace_memory_build.py`
- Test: `tests/test_memory_output_roots.py`

- [ ] **Step 1: Implement dry-run command generator**

The wrapper should initially support `--dry-run` only. It should print the exact commands for:

1. L1 extraction into `memory_outputs/grace/runs/grace_l1_<run_id>/share_mem`.
2. optimization v2 L2/L3 into the same run root under `l2_l3/`.
3. validation into `validation/`.

- [ ] **Step 2: Do not run API by default**

The default command must be dry-run unless `--execute` is explicitly passed.

- [ ] **Step 3: Run targeted tests**

```powershell
uv run python -m unittest tests.test_memory_output_roots
```

Expected: tests pass.

## Task 5: Add Documentation

**Files:**
- Modify: `optimization/TODO.md`
- Create: `optimization/OUTPUT_LAYOUT.md`

- [ ] **Step 1: Document the output contract**

Explain:

- canonical artifacts are read-only unless explicit promotion.
- ICSI output goes to `memory_outputs/icsi/runs/...`.
- Grace rerun output goes to `memory_outputs/grace/runs/...`.
- promotion candidate outputs are copied or exported only after validation.

- [ ] **Step 2: Add examples**

```powershell
uv run python share_mem/run_icsi_batch.py `
  --transcript-dir meeting_recording/transcript/ISCI `
  --output-base memory_outputs `
  --run-id batch03_20260605 `
  --transcript-glob "Bmr*.txt" `
  --line-limit 360 `
  --max-files 5 `
  --timeout-seconds 7200 `
  --continue-on-failure
```

```powershell
uv run python optimization/run_grace_memory_build.py `
  --output-base memory_outputs `
  --run-id grace_rebuild_20260605 `
  --dry-run
```

## Task 6: Verification Before Continuing BMR

**Files:**
- No code changes unless previous tasks require fixes.

- [ ] **Step 1: Confirm canonical has no generated diff**

```powershell
git diff --name-only -- share_mem/tree.json share_mem/meetings share_mem/l1_index.json share_mem/manifest.json long_term/l2 long_term/l3
```

Expected: no output.

- [ ] **Step 2: Run targeted tests**

```powershell
uv run python -m unittest tests.test_memory_output_roots tests.test_icsi_batch_orchestrator
```

Expected: tests pass.

- [ ] **Step 3: Run next ICSI batch using the unified output base**

```powershell
uv run python share_mem/run_icsi_batch.py `
  --transcript-dir meeting_recording/transcript/ISCI `
  --output-base memory_outputs `
  --run-id bmr012_016_first360_20260605 `
  --transcript-glob "Bmr*.txt" `
  --line-limit 360 `
  --max-files 5 `
  --timeout-seconds 7200 `
  --continue-on-failure
```

Expected: outputs land under `memory_outputs/icsi/runs/...`, not canonical.

## Self-Review

- The plan keeps raw canonical Grace artifacts separate from dataset outputs.
- The plan does not require changing L1/L2/L3 schema.
- The plan improves output hygiene before another long ICSI run.
- The plan keeps current `--output-root` compatibility.
- The plan creates a path for future Grace reruns without overwriting canonical.
