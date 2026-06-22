from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TAICHI_ROOT = REPO_ROOT / "doc" / "taichi"
DEMO_QUERY = (
    "What context about delay-and-sum beamforming and close microphones "
    "should carry over to later audio processing discussions?"
)


class TaichiDemoDocsTests(unittest.TestCase):
    def test_handoff_guide_documents_demo_boundary(self) -> None:
        guide = TAICHI_ROOT / "demo_handoff_guide.md"
        text = guide.read_text(encoding="utf-8")

        self.assertIn("uv run python memory_observatory/demo_health_check.py --dataset icsi", text)
        self.assertIn("optimization_v2_artifact", text)
        self.assertIn(DEMO_QUERY, text)
        self.assertIn("canonical `share_mem/`", text)
        self.assertIn("不能宣稱 generated answer quality", text)
        self.assertIn("LONG_TERM_BACKEND", text)

    def test_readiness_manifest_is_parseable_and_points_to_artifacts(self) -> None:
        manifest_path = TAICHI_ROOT / "demo_readiness_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["status"], "demo_ready_not_canonical_replacement")
        self.assertEqual(manifest["primary_dataset"], "icsi")
        self.assertEqual(manifest["resolved_backend_expected"], "optimization_v2_artifact")
        self.assertEqual(manifest["demo_query"], DEMO_QUERY)
        self.assertEqual(
            manifest["health_command"],
            "uv run python memory_observatory/demo_health_check.py --dataset icsi",
        )
        self.assertIn("l1_effective_share_mem", manifest["artifacts"])
        self.assertIn("l2_l3_runtime", manifest["artifacts"])
        self.assertIn("canonical runtime replacement", manifest["claim_boundary"]["not_allowed"])

    def test_artifact_index_links_handoff_assets(self) -> None:
        index = (TAICHI_ROOT / "artifact_index.md").read_text(encoding="utf-8")

        self.assertIn("doc/taichi/demo_handoff_guide.md", index)
        self.assertIn("doc/taichi/demo_readiness_manifest.json", index)

    def test_figure_inventory_identifies_final_paper_figures(self) -> None:
        inventory = (TAICHI_ROOT / "figure_inventory.md").read_text(encoding="utf-8")

        self.assertIn("Final Paper Selection", inventory)
        self.assertIn("memory_observatory_system_overview.png", inventory)
        self.assertIn("observatory_trace_icsi_focused.png", inventory)
        self.assertIn("observatory_topic_observatory_icsi.png", inventory)
        self.assertIn("observatory_memory_explorer_icsi.png", inventory)
        self.assertIn("observatory_presentation_icsi.png", inventory)

    def test_readiness_checklist_tracks_handoff_completion(self) -> None:
        checklist = (TAICHI_ROOT / "readiness_checklist.md").read_text(encoding="utf-8")

        self.assertIn("[x] Add partner handoff guide and machine-readable demo readiness manifest", checklist)

    def test_user_study_protocol_keeps_claim_boundary_clear(self) -> None:
        protocol = (TAICHI_ROOT / "user_study_pilot_protocol.md").read_text(encoding="utf-8")
        task_packet = (TAICHI_ROOT / "user_study_task_packet.md").read_text(encoding="utf-8")
        scoring_sheet = (TAICHI_ROOT / "user_study_scoring_sheet.csv").read_text(encoding="utf-8")

        self.assertIn("planned pilot", protocol.lower())
        self.assertIn("not completed user-study evidence", protocol.lower())
        self.assertIn("sidecar correction", protocol)
        self.assertIn("Retrieval Trace", task_packet)
        self.assertIn("Topic Observatory", task_packet)
        self.assertIn("Correction Review", task_packet)
        self.assertIn("participant_id,task_id", scoring_sheet)
        self.assertIn("correction_appropriateness", scoring_sheet)

    def test_transcript_span_benchmark_doc_distinguishes_gold_from_l1_alignment(self) -> None:
        spec = (TAICHI_ROOT / "icsi_transcript_span_benchmark_spec.md").read_text(encoding="utf-8")

        self.assertIn("L1 ids are allowed only as optional diagnostic alignment", spec)
        self.assertIn("primary gold evidence is a transcript span", spec)
        self.assertIn("held-out future-meeting carryover", spec)


if __name__ == "__main__":
    unittest.main()
