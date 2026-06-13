from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from optimization.long_term_v2.run_icsi_full_eval_pipeline import (
    ICSI_BMR_ABSENT_IDS,
    discover_completed_bmr_filtered_meetings,
    write_selected_effective_share_mem,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _filtered_root(
    runs_root: Path,
    name: str,
    meeting_ids: list[str],
    *,
    succeeded_ids: list[str] | None = None,
    failed_ids: list[str] | None = None,
    content_suffix: str = "",
) -> Path:
    run_root = runs_root / name
    filtered = run_root / "filtered_share_mem"
    meetings = []
    for meeting_id in meeting_ids:
        meetings.append(
            {
                "meeting_id": meeting_id,
                "timestamp": "2026-01-01T00:00:00Z",
                "meeting_date": "2026-01-01",
                "source_file": f"{meeting_id}.txt",
                "phase_id": "",
                "memory_objects": [
                    {
                        "obj_id": f"L1-{meeting_id}-001",
                        "type": "finding",
                        "legacy_type": "result",
                        "content": f"{meeting_id} effective content {content_suffix}".strip(),
                        "importance": 0.7,
                        "evidence": f"{meeting_id} evidence",
                        "related_topics": ["topic"],
                        "related_obj_ids": [],
                    }
                ],
            }
        )
    _write_json(
        filtered / "tree.json",
        {
            "tree_version": 1,
            "last_updated_utc": "2026-01-01T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": meetings,
        },
    )
    _write_json(
        filtered / "manifest.json",
        {
            "meeting_count": len(meeting_ids),
            "object_count": len(meeting_ids),
            "meeting_ids": meeting_ids,
        },
    )
    runs = []
    for meeting_id in failed_ids or []:
        runs.append({"meeting_id": meeting_id, "status": "failed"})
    for meeting_id in succeeded_ids if succeeded_ids is not None else meeting_ids:
        runs.append({"meeting_id": meeting_id, "status": "succeeded"})
    _write_json(run_root / "batch_status.json", {"schema_version": 1, "runs": runs})
    return filtered


class IcsiFullEvalPipelineTests(unittest.TestCase):
    def test_discovery_ignores_first360_probe_and_selects_full_filtered_meetings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _filtered_root(root, "bmr001_full_20260614", ["Bmr001"])
            _filtered_root(root, "bmr002_first360_20260614", ["Bmr002"])
            _filtered_root(root, "bmr002_full_probe_20260614", ["Bmr002"])
            _filtered_root(root, "bmr002_full_20260614", ["Bmr002"])

            discovery = discover_completed_bmr_filtered_meetings(
                runs_root=root,
                expected_meeting_ids=["Bmr001", "Bmr002"],
            )

            self.assertEqual(discovery["missing_meeting_ids"], [])
            self.assertEqual(set(discovery["selected_meetings"]), {"Bmr001", "Bmr002"})
            self.assertNotIn("first360", discovery["meeting_sources"]["Bmr002"]["run_root"])
            self.assertNotIn("probe", discovery["meeting_sources"]["Bmr002"]["run_root"])

    def test_discovery_accepts_shared_root_with_old_failed_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _filtered_root(
                root,
                "bmr020_bmr022_full_shared_20260614",
                ["Bmr020", "Bmr022"],
                failed_ids=["Bmr020"],
                succeeded_ids=["Bmr020", "Bmr022"],
            )

            discovery = discover_completed_bmr_filtered_meetings(
                runs_root=root,
                expected_meeting_ids=["Bmr020", "Bmr022"],
            )

            self.assertEqual(discovery["missing_meeting_ids"], [])
            self.assertEqual(set(discovery["selected_meetings"]), {"Bmr020", "Bmr022"})

    def test_discovery_prefers_newer_retry_for_duplicate_meeting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = _filtered_root(root, "bmr011_full_retry1_20260612", ["Bmr011"], content_suffix="old")
            new = _filtered_root(root, "bmr011_full_retry2_20260614", ["Bmr011"], content_suffix="new")
            old.joinpath("manifest.json").touch()
            new.joinpath("manifest.json").touch()

            discovery = discover_completed_bmr_filtered_meetings(
                runs_root=root,
                expected_meeting_ids=["Bmr011"],
            )

            self.assertEqual(discovery["selected_meetings"], ["Bmr011"])
            self.assertIn("retry2", discovery["meeting_sources"]["Bmr011"]["run_root"])
            meeting = discovery["selected_meeting_payloads"]["Bmr011"]
            self.assertIn("new", meeting["memory_objects"][0]["content"])

    def test_missing_required_meeting_fails_unless_allow_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _filtered_root(root, "bmr001_full_20260614", ["Bmr001"])

            with self.assertRaises(ValueError):
                discover_completed_bmr_filtered_meetings(
                    runs_root=root,
                    expected_meeting_ids=["Bmr001", "Bmr002"],
                )

            discovery = discover_completed_bmr_filtered_meetings(
                runs_root=root,
                expected_meeting_ids=["Bmr001", "Bmr002"],
                allow_missing=True,
            )
            self.assertEqual(discovery["missing_meeting_ids"], ["Bmr002"])

    def test_write_selected_effective_share_mem_outputs_sidecar_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _filtered_root(root, "bmr001_full_20260614", ["Bmr001"])
            discovery = discover_completed_bmr_filtered_meetings(
                runs_root=root,
                expected_meeting_ids=["Bmr001"],
            )

            report = write_selected_effective_share_mem(
                discovery=discovery,
                output_root=root / "combined",
                clean=True,
            )

            tree_path = Path(report["share_mem_effective_root"]) / "tree.json"
            self.assertTrue(tree_path.exists())
            tree = json.loads(tree_path.read_text(encoding="utf-8"))
            self.assertEqual(tree["meetings"][0]["meeting_id"], "Bmr001")
            self.assertEqual(report["summary"]["meeting_count"], 1)
            self.assertTrue(str(report["share_mem_effective_root"]).endswith("share_mem_effective"))

    def test_default_expected_ids_exclude_known_absent_bmr_files(self) -> None:
        self.assertEqual(ICSI_BMR_ABSENT_IDS, {"Bmr004", "Bmr017"})


if __name__ == "__main__":
    unittest.main()
