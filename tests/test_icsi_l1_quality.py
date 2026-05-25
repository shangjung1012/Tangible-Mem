from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from share_mem.validate_icsi_l1 import (
    build_icsi_l1_review_gate,
    build_icsi_l1_quality_report,
    write_icsi_l1_quality_report,
    write_icsi_l1_review_gate,
)


def _obj(
    obj_id: str,
    *,
    obj_type: str = "finding",
    content: str,
    evidence: str,
    importance: float = 0.5,
    topics: list[str] | None = None,
) -> dict:
    return {
        "obj_id": obj_id,
        "type": obj_type,
        "legacy_type": "result",
        "content": content,
        "evidence": evidence,
        "importance": importance,
        "related_topics": topics or [],
        "related_obj_ids": [],
        "meeting_id": "Bdb001",
    }


class ICSIQualityTests(unittest.TestCase):
    def test_report_flags_setup_noise_duplicates_and_topic_aliases(self) -> None:
        shared_evidence = (
            "[me011]: We already have an XML format for word transcripts, "
            "annotations, and time-marks."
        )
        objects = [
            _obj(
                "L1-Bdb001-001",
                content=(
                    "The recording counter is not moving during the local equipment "
                    "setup."
                ),
                evidence="[fe016]: The counter is not moving again.",
                importance=0.68,
                topics=["recording equipment", "setup"],
            ),
            _obj(
                "L1-Bdb001-002",
                content=(
                    "The group needs a database format linking transcripts, "
                    "annotations, and time-marks."
                ),
                evidence=shared_evidence,
                importance=0.76,
                topics=["database format", "xml schema"],
            ),
            _obj(
                "L1-Bdb001-003",
                obj_type="proposal",
                content=(
                    "Using the existing XML format was proposed as a way to link "
                    "transcripts, annotations, and time-marks."
                ),
                evidence=shared_evidence,
                importance=0.72,
                topics=["data format", "annotation format"],
            ),
        ]

        report = build_icsi_l1_quality_report(objects)

        self.assertEqual(report["summary"]["object_count"], 3)
        self.assertEqual(report["summary"]["setup_noise_count"], 1)
        self.assertEqual(report["summary"]["high_importance_setup_count"], 1)
        self.assertEqual(report["summary"]["same_evidence_duplicate_group_count"], 1)
        self.assertEqual(report["summary"]["topic_alias_cluster_count"], 1)
        self.assertEqual(objects[2]["type"], "proposal")
        self.assertNotIn("auto_reclassified_decisions", report)

    def test_report_flags_non_english_content_without_mutating_object(self) -> None:
        objects = [
            _obj(
                "L1-Bdb001-004",
                content="這個 content 不應該出現在 ICSI 英文輸出。",
                evidence="[me011]: English evidence.",
                topics=["annotation format"],
            )
        ]

        report = build_icsi_l1_quality_report(objects)

        self.assertEqual(report["summary"]["content_language_violation_count"], 1)
        self.assertEqual(objects[0]["content"], "這個 content 不應該出現在 ICSI 英文輸出。")

    def test_review_gate_marks_source_data_and_duplicate_merge_candidates(self) -> None:
        shared_evidence = "[me011]: Fill it out. [me013]: Why are we writing it down?"
        objects = [
            _obj(
                "L1-Bmr001-001",
                content=(
                    "The microphone inventory identified the wired headset, wireless "
                    "microphone, lapel microphone, and dummy PDA channels."
                ),
                evidence="[me025]: Let's name the microphones.",
                importance=0.69,
                topics=["microphone inventory", "recording setup"],
            ),
            _obj(
                "L1-Bmr001-002",
                obj_type="decision",
                content="Participants must write metadata on the form and not say it aloud.",
                evidence=shared_evidence,
                importance=0.71,
                topics=["data collection protocol", "metadata"],
            ),
            _obj(
                "L1-Bmr001-003",
                obj_type="finding",
                content="Written metadata helps later speaker identification.",
                evidence=shared_evidence,
                importance=0.67,
                topics=["metadata", "speaker identification"],
            ),
        ]

        gate = build_icsi_l1_review_gate(objects)

        self.assertEqual(gate["summary"]["object_count"], 3)
        self.assertEqual(gate["summary"]["drop_candidate_count"], 1)
        self.assertEqual(gate["summary"]["merge_review_group_count"], 1)
        self.assertIn("L1-Bmr001-001", gate["drop_candidate_obj_ids"])
        self.assertIn("L1-Bmr001-002", gate["filtered_candidate_obj_ids"])
        self.assertNotIn("L1-Bmr001-001", gate["filtered_candidate_obj_ids"])
        self.assertEqual(objects[1]["type"], "decision")
        self.assertNotIn("auto_reclassified_decisions", gate)
        duplicate = gate["duplicate_reviews"][0]
        self.assertEqual(duplicate["recommended_keep_obj_id"], "L1-Bmr001-002")
        self.assertIn("L1-Bmr001-003", duplicate["merge_candidate_obj_ids"])

    def test_write_review_gate_outputs_sidecar_and_filtered_view(self) -> None:
        objects = [
            _obj(
                "L1-Bmr001-004",
                content="The recording begins by formally stating meeting metadata and participant names.",
                evidence="[me013]: Meeting number one with Adam and Dan.",
                importance=0.56,
                topics=["meeting metadata"],
            ),
            _obj(
                "L1-Bmr001-005",
                content="The protocol requires speakers to pause between digit lines.",
                evidence="[me011]: Pause between each line since we will segment it.",
                importance=0.7,
                topics=["data collection protocol"],
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_icsi_l1_review_gate(objects, out)

            gate_path = out / "icsi_l1_review_gate.json"
            view_path = out / "icsi_l1_filtered_view.json"
            md_path = out / "icsi_l1_review_gate.md"
            self.assertTrue(gate_path.exists())
            self.assertTrue(view_path.exists())
            self.assertTrue(md_path.exists())
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
            filtered = json.loads(view_path.read_text(encoding="utf-8"))
            self.assertEqual(gate["summary"]["drop_candidate_count"], 1)
            self.assertEqual(
                [obj["obj_id"] for obj in filtered["memory_objects"]],
                ["L1-Bmr001-005"],
            )
            self.assertEqual(
                objects[0]["content"],
                "The recording begins by formally stating meeting metadata and participant names.",
            )

    def test_review_gate_does_not_recommend_dropped_duplicate_as_keep(self) -> None:
        shared_evidence = "[me025]: Let's name the microphones for the recording."
        objects = [
            _obj(
                "L1-Bmr001-006",
                content=(
                    "The microphone inventory listed the wired headset, wireless "
                    "microphone, lapel microphone, and dummy PDA."
                ),
                evidence=shared_evidence,
                importance=0.9,
                topics=["microphone inventory", "recording setup"],
            ),
            _obj(
                "L1-Bmr001-007",
                obj_type="approach_change",
                content=(
                    "The recording protocol maps microphone sources to speakers "
                    "for later corpus indexing."
                ),
                evidence=shared_evidence,
                importance=0.65,
                topics=["recording protocol", "corpus metadata"],
            ),
        ]

        gate = build_icsi_l1_review_gate(objects)

        self.assertIn("L1-Bmr001-006", gate["drop_candidate_obj_ids"])
        self.assertEqual(
            gate["duplicate_reviews"][0]["recommended_keep_obj_id"],
            "L1-Bmr001-007",
        )
        self.assertIn("L1-Bmr001-007", gate["filtered_candidate_obj_ids"])

    def test_review_gate_keeps_durable_recording_methodology(self) -> None:
        objects = [
            _obj(
                "L1-Bed002-001",
                obj_type="decision",
                content=(
                    "All near-field and far-field microphone channels will be "
                    "recorded frame-synchronously to support ASR evaluation."
                ),
                evidence=(
                    "[me011]: We should record all microphone channels "
                    "frame-synchronously so the far-field speech recognition "
                    "results can be compared."
                ),
                importance=0.78,
                topics=["recording data quality", "speech recognition evaluation"],
            )
        ]

        gate = build_icsi_l1_review_gate(objects)

        self.assertEqual(gate["summary"]["drop_candidate_count"], 0)
        self.assertIn("L1-Bed002-001", gate["filtered_candidate_obj_ids"])

    def test_write_report_outputs_json_and_markdown(self) -> None:
        objects = [
            _obj(
                "L1-Bdb001-005",
                content="A reusable annotation data model was discussed.",
                evidence="[me011]: XML format for annotations.",
                topics=["xml format"],
            )
        ]

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_icsi_l1_quality_report(objects, out)

            report_path = out / "icsi_l1_quality_report.json"
            md_path = out / "icsi_l1_quality_report.md"
            self.assertTrue(report_path.exists())
            self.assertTrue(md_path.exists())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["object_count"], 1)
            self.assertIn("ICSI L1 Quality Report", md_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
