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
        self.assertIn("L1-Bmr001-003", duplicate["manual_review_obj_ids"])
        self.assertIn("L1-Bmr001-003", gate["filtered_candidate_obj_ids"])

    def test_low_similarity_same_evidence_duplicates_stay_in_filtered_view(self) -> None:
        shared_evidence = (
            "[me018]: You can tell if it is picking up breath noise. "
            "[me011]: The AF indicator lights up. "
            "[fe016]: But we still do not know how to remove the noise."
        )
        objects = [
            _obj(
                "L1-Bdb001-010",
                obj_type="approach_change",
                content=(
                    "A method was identified for detecting breath and mouth noises "
                    "in real time using the AF indicator."
                ),
                evidence=shared_evidence,
                importance=0.60,
                topics=["recording data quality", "breath noise detection"],
            ),
            _obj(
                "L1-Bdb001-011",
                obj_type="open_issue",
                content=(
                    "The audio recordings contain breath and mouth noise, and it "
                    "remains unresolved how that noise will be mitigated or removed."
                ),
                evidence=shared_evidence,
                importance=0.54,
                topics=["recording data quality", "noise reduction"],
            ),
        ]

        gate = build_icsi_l1_review_gate(objects)

        self.assertEqual(gate["summary"]["merge_candidate_count"], 0)
        self.assertEqual(gate["summary"]["duplicate_review_candidate_count"], 1)
        self.assertIn("L1-Bdb001-010", gate["filtered_candidate_obj_ids"])
        self.assertIn("L1-Bdb001-011", gate["filtered_candidate_obj_ids"])
        self.assertIn("L1-Bdb001-011", gate["duplicate_reviews"][0]["manual_review_obj_ids"])

    def test_same_evidence_distinct_xml_claims_need_review_not_merge(self) -> None:
        shared_evidence = (
            "[me011]: I sort of already have developed an XML format for this "
            "sort of stuff. [me018]: Can I see it? [me011]: The only question "
            "is it the sort of thing that you want to use or not? Have you "
            "looked at that? I had a web page up."
        )
        objects = [
            _obj(
                "L1-Bdb001-020",
                obj_type="action_item",
                content=(
                    "The group needs to review the existing XML format and "
                    "its associated web page to evaluate it as a potential "
                    "database format for linking various data types."
                ),
                evidence=shared_evidence,
                importance=0.63,
                topics=["annotation data model", "xml format"],
            ),
            _obj(
                "L1-Bdb001-021",
                obj_type="finding",
                content=(
                    "A participant has already developed a relevant XML format "
                    "for linking various data types and has made it available "
                    "via a web page."
                ),
                evidence=shared_evidence,
                importance=0.62,
                topics=["annotation data model", "xml format"],
            ),
        ]

        gate = build_icsi_l1_review_gate(objects)

        self.assertEqual(gate["summary"]["merge_candidate_count"], 0)
        self.assertEqual(gate["summary"]["duplicate_review_candidate_count"], 1)
        self.assertIn("L1-Bdb001-020", gate["filtered_candidate_obj_ids"])
        self.assertIn("L1-Bdb001-021", gate["filtered_candidate_obj_ids"])
        self.assertIn("L1-Bdb001-021", gate["duplicate_reviews"][0]["manual_review_obj_ids"])

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

    def test_review_gate_keeps_ground_truth_microphone_methodology(self) -> None:
        objects = [
            _obj(
                "L1-Bed002-003",
                obj_type="action_item",
                content=(
                    "The project's data collection approach uses tabletop PZM "
                    "microphones and close-talking microphones. The close-talking "
                    "mics provide ground truth high-quality audio so language-focused "
                    "research is not penalized by far-field audio quality."
                ),
                evidence=(
                    "[me011]: The close-talking mics give us some ground truth, "
                    "high quality audio, especially for people interested in "
                    "language rather than recognition."
                ),
                importance=0.72,
                topics=[
                    "data collection",
                    "recording data quality",
                    "ground truth",
                    "far-field audio",
                    "close-talking audio",
                    "recording setup",
                ],
            )
        ]

        gate = build_icsi_l1_review_gate(objects)

        self.assertEqual(gate["summary"]["drop_candidate_count"], 0)
        self.assertIn("L1-Bed002-003", gate["filtered_candidate_obj_ids"])

    def test_review_gate_does_not_flag_belief_net_probability_setup_as_setup_noise(self) -> None:
        objects = [
            _obj(
                "L1-Bed003-001",
                obj_type="argument",
                content=(
                    "A big-flat belief-net model was criticized because setting "
                    "up the probabilities would be impractical. The setup of "
                    "probabilities would be exponentially complex and would "
                    "handicap later learning steps."
                ),
                evidence=(
                    "[me003]: The initial idea was all features pointing to the "
                    "output node. It would be a pain to set up all the probabilities."
                ),
                importance=0.67,
                topics=[
                    "belief-net model",
                    "model architecture",
                    "machine learning",
                    "computational complexity",
                ],
            )
        ]

        gate = build_icsi_l1_review_gate(objects)

        self.assertEqual(gate["summary"]["review_candidate_count"], 0)
        self.assertIn("L1-Bed003-001", gate["filtered_candidate_obj_ids"])

    def test_review_gate_does_not_flag_anonymization_policy_as_setup_noise(self) -> None:
        objects = [
            _obj(
                "L1-Bed002-002",
                obj_type="finding",
                content=(
                    "The strategy for handling sensitive content is transcript "
                    "anonymization plus post-processing edits, rather than asking "
                    "participants to self-censor during recording."
                ),
                evidence=(
                    "[me010]: In terms of people worrying about excising things "
                    "from the transcript, it is unlikely since it is not attributed."
                ),
                importance=0.57,
                topics=["data handling", "anonymization", "content moderation"],
            )
        ]

        gate = build_icsi_l1_review_gate(objects)

        self.assertEqual(gate["summary"]["review_candidate_count"], 0)
        self.assertIn("L1-Bed002-002", gate["filtered_candidate_obj_ids"])

    def test_review_gate_does_not_flag_audio_quality_failure_as_setup_noise(self) -> None:
        objects = [
            _obj(
                "L1-Bmr001-020",
                obj_type="finding",
                content=(
                    "The custom-built amplifier prototype was found to be too "
                    "noisy and clumsy, creating an audio quality hardware issue."
                ),
                evidence=(
                    "[me025]: I built this thing, but it is very noisy, so I am "
                    "using another pre-amp as an alternative."
                ),
                importance=0.66,
                topics=["audio quality", "hardware issue", "equipment failure"],
            )
        ]

        gate = build_icsi_l1_review_gate(objects)

        self.assertEqual(gate["summary"]["review_candidate_count"], 0)
        self.assertIn("L1-Bmr001-020", gate["filtered_candidate_obj_ids"])

    def test_review_gate_drops_microphone_inventory_even_when_labeled_protocol(self) -> None:
        objects = [
            _obj(
                "L1-Bmr001-008",
                obj_type="approach_change",
                content=(
                    "A procedure was adopted for microphone checks where participants "
                    "identify their assigned channel number and microphone type. "
                    "Stationary PZM microphones and a dummy PDA were also identified "
                    "to complete the audio setup mapping."
                ),
                evidence=(
                    "[me025]: Let's name the microphones. "
                    "[me011]: I'm now talking on microphone number two. "
                    "[me025]: This is the PZM nearest the machine room end. "
                    "[me025]: This is the left side of the dummy PDA."
                ),
                importance=0.64,
                topics=["recording procedure", "recording protocol", "microphone technique"],
            )
        ]

        gate = build_icsi_l1_review_gate(objects)

        self.assertEqual(gate["summary"]["drop_candidate_count"], 1)
        self.assertIn("L1-Bmr001-008", gate["drop_candidate_obj_ids"])
        self.assertNotIn("L1-Bmr001-008", gate["filtered_candidate_obj_ids"])

    def test_review_gate_drops_microphone_inventory_with_generic_corpus_topics(self) -> None:
        objects = [
            _obj(
                "L1-Bmr001-021",
                obj_type="finding",
                content=(
                    "The recording setup for this session includes a mix of "
                    "close-talking and far-field microphones: an ear-mounted wired "
                    "headset, a wireless microphone, a lapel microphone, three PZM "
                    "tabletop microphones, and a dummy PDA device."
                ),
                evidence=(
                    "[me013]: What's this one here? [me025]: That's the dummy PDA. "
                    "[me011]: Both channels. [me025]: I'm speaking on the ear mount."
                ),
                importance=0.53,
                topics=[
                    "data collection",
                    "microphone usage",
                    "corpus design",
                    "far-field audio",
                    "close-talking audio",
                    "pda device",
                ],
            )
        ]

        gate = build_icsi_l1_review_gate(objects)

        self.assertEqual(gate["summary"]["drop_candidate_count"], 1)
        self.assertIn("L1-Bmr001-021", gate["drop_candidate_obj_ids"])
        self.assertNotIn("L1-Bmr001-021", gate["filtered_candidate_obj_ids"])

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
