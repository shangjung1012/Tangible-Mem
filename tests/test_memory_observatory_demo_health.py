from __future__ import annotations

import tempfile
import unittest
import subprocess
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from fastapi.testclient import TestClient

from memory_observatory.demo_health_check import run_cli
from memory_observatory.main import create_app
from tests.test_memory_observatory import _fixture_icsi_dataset, _fixture_repo

REPO_ROOT = Path(__file__).resolve().parents[1]


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
            self.assertEqual(payload["resolved_backend"], "optimization_v2_artifact")

    def test_demo_health_fails_for_missing_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture_repo(root)
            client = TestClient(create_app(root))

            response = client.get("/api/demo/health?dataset=unknown")

            self.assertEqual(response.status_code, 404)

    def test_demo_health_cli_returns_zero_for_ready_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture_repo(root)
            _fixture_icsi_dataset(root)

            with redirect_stdout(StringIO()):
                exit_code = run_cli(["--repo-root", str(root), "--dataset", "icsi"])

            self.assertEqual(exit_code, 0)

    def test_demo_health_cli_can_run_as_script_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture_repo(root)
            _fixture_icsi_dataset(root)

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "memory_observatory" / "demo_health_check.py"),
                    "--repo-root",
                    str(root),
                    "--dataset",
                    "icsi",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"resolved_backend": "optimization_v2_artifact"', result.stdout)


if __name__ == "__main__":
    unittest.main()
