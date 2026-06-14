from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from optimization.long_term_v2.create_icsi_eval_pack import create_icsi_eval_pack


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _obj(obj_id: str, content: str, *, meeting_id: str, obj_type: str = "finding") -> dict:
    return {
        "obj_id": obj_id,
        "type": obj_type,
        "legacy_type": "result",
        "content": content,
        "importance": 0.72,
        "evidence": content,
        "related_topics": ["audio processing"],
        "related_obj_ids": [],
        "_meeting_id": meeting_id,
    }


def _meeting(meeting_id: str, objects: list[dict]) -> dict:
    return {
        "meeting_id": meeting_id,
        "timestamp": "2026-01-01T00:00:00Z",
        "meeting_date": "2026-01-01",
        "source_file": f"{meeting_id}.txt",
        "phase_id": "",
        "memory_objects": [
            {key: value for key, value in obj.items() if key != "_meeting_id"}
            for obj in objects
        ],
    }


def _fixture(root: Path) -> tuple[Path, Path]:
    share = root / "memory_outputs" / "icsi" / "runs" / "fixture" / "share_mem_effective"
    source_objs = [
        _obj("L1-Bmr001-001", "The team discussed audio processing filters for meeting recordings.", meeting_id="Bmr001"),
        _obj("L1-Bmr002-001", "A decision was made to preserve audio channel metadata for later analysis.", meeting_id="Bmr002", obj_type="decision"),
    ]
    heldout_objs = [
        _obj("L1-Bmr024-001", "Later meetings revisited audio processing because channel alignment remained fragile.", meeting_id="Bmr024"),
        _obj("L1-Bmr025-001", "The group carried forward audio channel issues into a later recording workflow.", meeting_id="Bmr025"),
    ]
    weak_objs = [
        _obj("L1-Bmr001-weak", "The speaker said go ahead during a transition.", meeting_id="Bmr001"),
        _obj("L1-Bmr024-weak", "The phrase go ahead appeared again.", meeting_id="Bmr024"),
    ]
    tree = {
        "tree_version": 1,
        "last_updated_utc": "2026-01-01T00:00:00Z",
        "project_profile": {},
        "phases": [],
        "meetings": [
            _meeting("Bmr001", [source_objs[0], weak_objs[0]]),
            _meeting("Bmr002", [source_objs[1]]),
            _meeting("Bmr024", [heldout_objs[0], weak_objs[1]]),
            _meeting("Bmr025", [heldout_objs[1]]),
        ],
    }
    _write_json(share / "tree.json", tree)
    _write_json(share / "manifest.json", {"meeting_count": 4, "object_count": 6, "meeting_ids": ["Bmr001", "Bmr002", "Bmr024", "Bmr025"]})
    for meeting in tree["meetings"]:
        _write_json(share / "meetings" / f"{meeting['meeting_id']}.json", meeting)

    run = root / "optimization" / "runs" / "fixture_v2"
    l2_nodes = [
        {
            "l2_id": "L2-audio-processing",
            "label": "audio processing",
            "linked_obj_ids": ["L1-Bmr001-001", "L1-Bmr002-001", "L1-Bmr024-001", "L1-Bmr025-001"],
            "meeting_ids": ["Bmr001", "Bmr002", "Bmr024", "Bmr025"],
            "timeline_digest": [
                {"obj_id": "L1-Bmr001-001", "meeting_id": "Bmr001", "summary": "audio filters"},
                {"obj_id": "L1-Bmr024-001", "meeting_id": "Bmr024", "summary": "alignment remained fragile"},
            ],
        },
        {
            "l2_id": "L2-go-ahead",
            "label": "go ahead",
            "linked_obj_ids": ["L1-Bmr001-weak", "L1-Bmr024-weak"],
            "meeting_ids": ["Bmr001", "Bmr024"],
            "timeline_digest": [],
        },
        {
            "l2_id": "L2-team-decided",
            "label": "team decided",
            "linked_obj_ids": ["L1-Bmr001-001", "L1-Bmr002-001", "L1-Bmr024-001"],
            "meeting_ids": ["Bmr001", "Bmr002", "Bmr024"],
            "timeline_digest": [],
        },
    ]
    l2_index = {
        "L1-Bmr001-001": {"l2_id": "L2-audio-processing", "l2_label": "audio processing"},
        "L1-Bmr002-001": {"l2_id": "L2-audio-processing", "l2_label": "audio processing"},
        "L1-Bmr024-001": {"l2_id": "L2-audio-processing", "l2_label": "audio processing"},
        "L1-Bmr025-001": {"l2_id": "L2-audio-processing", "l2_label": "audio processing"},
        "L1-Bmr001-weak": {"l2_id": "L2-go-ahead", "l2_label": "go ahead"},
        "L1-Bmr024-weak": {"l2_id": "L2-go-ahead", "l2_label": "go ahead"},
    }
    _write_json(run / "manifest.json", {"profile_path": str(Path("optimization/long_term_v2/profiles/isci_meeting.yaml").resolve())})
    _write_json(run / "l2" / "l2_view.json", {"l2_nodes": l2_nodes})
    _write_json(run / "l2" / "l2_index.json", l2_index)
    _write_json(run / "l3" / "l3_view.json", {"l3_parents": []})
    _write_json(run / "l3" / "l3_index.json", {})
    return run, share


class IcsiEvalPackTests(unittest.TestCase):
    def test_eval_pack_uses_heldout_as_trigger_and_source_as_answerable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run, share = _fixture(Path(tmp))
            out = Path(tmp) / "optimization" / "reports" / "icsi_eval_pack"

            report = create_icsi_eval_pack(
                run_root=run,
                share_mem_root=share,
                out_dir=out,
                source_through_meeting_id="Bmr023",
                max_questions=5,
            )

            self.assertEqual(report["status"], "candidate_manual_review_required")
            self.assertEqual(report["query_count"], 5)
            self.assertTrue((out / "heldout_eval_queries.jsonl").exists())
            self.assertTrue((out / "source_share_mem" / "tree.json").exists())
            source_tree = json.loads((out / "source_share_mem" / "tree.json").read_text(encoding="utf-8"))
            self.assertEqual([meeting["meeting_id"] for meeting in source_tree["meetings"]], ["Bmr001", "Bmr002"])
            rows = [
                json.loads(line)
                for line in (out / "heldout_eval_queries.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(all(row["benchmark_type"] == "heldout_future_meeting" for row in rows))
            self.assertTrue(all(row["expected_obj_ids"] == row["expected_source_obj_ids"] for row in rows))
            self.assertTrue(all(obj_id.startswith("L1-Bmr00") for row in rows for obj_id in row["expected_source_obj_ids"]))
            self.assertTrue(all(obj_id.startswith("L1-Bmr02") for row in rows for obj_id in row["heldout_trigger_obj_ids"]))
            self.assertEqual({row["expected_l2_labels"][0] for row in rows}, {"audio processing"})
            self.assertIn("manual review", (out / "heldout_eval_pack.md").read_text(encoding="utf-8").lower())

    def test_eval_pack_filters_weak_labels_and_requires_pre_post_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run, share = _fixture(Path(tmp))
            out = Path(tmp) / "optimization" / "reports" / "icsi_eval_pack"

            report = create_icsi_eval_pack(
                run_root=run,
                share_mem_root=share,
                out_dir=out,
                source_through_meeting_id="Bmr023",
                max_questions=10,
            )

            labels = {label for row in report["queries"] for label in row["expected_l2_labels"]}
            self.assertNotIn("go ahead", labels)
            self.assertNotIn("team decided", labels)
            self.assertEqual(labels, {"audio processing"})


if __name__ == "__main__":
    unittest.main()
