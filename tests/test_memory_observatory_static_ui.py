from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class MemoryObservatoryStaticUiTests(unittest.TestCase):
    def test_overview_has_dataset_switch_and_icsi_result_copy(self) -> None:
        html = (REPO_ROOT / "memory_observatory" / "static" / "index.html").read_text(encoding="utf-8")
        js = (REPO_ROOT / "memory_observatory" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("datasetSwitch", html)
        self.assertIn("Grace", html)
        self.assertIn("ICSI", html)
        self.assertIn("ICSI Large-Corpus Memory Observatory", js)
        self.assertIn("Layered Memory retrieves more expected evidence in this diagnostic", js)
        self.assertIn("loadIcsiScaleResult", js)

    def test_retrieval_trace_describes_l1_seed_search_modes(self) -> None:
        html = (REPO_ROOT / "memory_observatory" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn("Hybrid L1 seed search (lexical + semantic when available)", html)
        self.assertIn("Lexical L1 seed search (offline)", html)
        self.assertIn("Semantic L1 seed search (embedding API)", html)
        self.assertIn("L2 / child-L2 / L3 expansion then follows layered retrieval rules", html)
        self.assertIn("Hybrid fuses lexical hits with semantic hits when an embedding client is available", html)

    def test_no_llm_planner_ui_hides_flash_as_active_model(self) -> None:
        html = (REPO_ROOT / "memory_observatory" / "static" / "index.html").read_text(encoding="utf-8")
        js = (REPO_ROOT / "memory_observatory" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn('value="gemini-2.5-flash"', html)
        self.assertIn("syncTracePlannerControl", js)
        self.assertIn("tracePlannerModel.disabled = noLlm", js)
        self.assertIn("Heuristic planner: no model call", js)
        self.assertIn("traceModeLabel(mode)", js)
        self.assertNotIn("`planner: ${data.planner_model", js)

    def test_retrieval_trace_l2_cards_have_drilldown(self) -> None:
        js = (REPO_ROOT / "memory_observatory" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("renderTraceL2Card", js)
        self.assertIn("loadTraceL2Detail", js)
        self.assertIn("/api/topics/l2/", js)
        self.assertIn("Selected in this trace", js)
        self.assertIn("Full L2 topic", js)
        self.assertIn("traceL2Detail", js)

    def test_retrieval_trace_demo_order_starts_from_l1_before_topic_map(self) -> None:
        js = (REPO_ROOT / "memory_observatory" / "static" / "app.js").read_text(encoding="utf-8")
        run_trace = js[js.index("async function runTrace()") : js.index("async function loadExplorer()")]

        self.assertLess(
            run_trace.index('listSection("L1 Evidence Seeds"'),
            run_trace.index("renderTraceGlobalTopicMap"),
        )
        self.assertLess(
            run_trace.index('listSection("L2 / Child-L2 Evolution Context"'),
            run_trace.index("renderTraceL3Navigation"),
        )
        self.assertIn("renderTraceDebugPanel", run_trace)

    def test_retrieval_trace_renders_compact_topic_map_and_parent_l3(self) -> None:
        js = (REPO_ROOT / "memory_observatory" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function renderTraceGlobalTopicMap", js)
        self.assertIn("Navigation context only", js)
        self.assertIn("function renderTraceL3Navigation", js)
        self.assertIn("Parent L3 Navigation", js)
        self.assertIn("prompt budget", js)
        self.assertNotIn('section("Global Topic Map", JSON.stringify(data.global_topic_map', js)

    def test_retrieval_trace_renders_icsi_demo_query_buttons_and_dataset(self) -> None:
        html = (REPO_ROOT / "memory_observatory" / "static" / "index.html").read_text(encoding="utf-8")
        js = (REPO_ROOT / "memory_observatory" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("data-demo-query", html)
        self.assertIn("audio processing", html)
        self.assertIn("annotation tool workflow", html)
        self.assertIn("function renderTraceRouter", js)
        self.assertIn("Router / Memory Layers", js)
        self.assertIn("Long-term memory", js)
        self.assertIn("data.router_result", js)
        self.assertIn("dataset=${selectedDataset}", js)
        self.assertNotIn("Short-Term Memory", js)
        self.assertNotIn("short_term_context", js)
        self.assertNotIn("?桀?", html)

    def test_retrieval_trace_can_switch_compact_and_paper_profiles(self) -> None:
        html = (REPO_ROOT / "memory_observatory" / "static" / "index.html").read_text(encoding="utf-8")
        js = (REPO_ROOT / "memory_observatory" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("show debug panel", html)
        self.assertIn("traceBudgetProfile", html)
        self.assertIn("observatory_trace", html)
        self.assertIn("observatory_paper_trace", html)
        self.assertIn('const budgetProfile = $("#traceBudgetProfile").value', js)
        self.assertIn("const maxContextChars = budgetProfile === \"observatory_paper_trace\" ? 0 : 16000", js)
        self.assertIn("max_context_chars=${maxContextChars}", js)
        self.assertIn("budget_profile=${budgetProfile}", js)
        self.assertIn("include_debug=false", js)
        self.assertIn("budget profile: ${budgetProfile}", js)
        self.assertIn('$("#traceMode").value = "lexical"', js)

    def test_presentation_story_uses_icsi_demo_query_and_dataset(self) -> None:
        html = (REPO_ROOT / "memory_observatory" / "static" / "presentation.html").read_text(encoding="utf-8")
        js = (REPO_ROOT / "memory_observatory" / "static" / "presentation.js").read_text(encoding="utf-8")

        self.assertIn("What context about delay-and-sum beamforming and close microphones", html)
        self.assertIn("What context about delay-and-sum beamforming and close microphones", js)
        self.assertIn("dataset=icsi", js)
        self.assertIn("retrieval_mode=lexical", js)
        self.assertIn("audio acquisition and signal processing", js)
        self.assertIn("max_context_chars=0", js)
        self.assertNotIn("idea units", html)
        self.assertNotIn("idea units", js)
        self.assertNotIn("dataset=grace", html)
        self.assertNotIn("dataset=grace", js)

    def test_demo_story_renders_health_panel(self) -> None:
        html = (REPO_ROOT / "memory_observatory" / "static" / "index.html").read_text(encoding="utf-8")
        js = (REPO_ROOT / "memory_observatory" / "static" / "app.js").read_text(encoding="utf-8")
        css = (REPO_ROOT / "memory_observatory" / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("demoHealth", html)
        self.assertIn("renderDemoHealth", js)
        self.assertIn("healthCheckLabel", js)
        self.assertIn("/api/demo/health", js)
        self.assertIn("resolved_backend", js)
        self.assertIn("demo-health-card", css)
        self.assertIn("health-check-grid", css)

    def test_readme_documents_current_trace_and_experiment_defaults(self) -> None:
        readme = (REPO_ROOT / "memory_observatory" / "README.md").read_text(encoding="utf-8")

        self.assertIn("UI Retrieval Trace demo profile", readme)
        self.assertIn("observatory_trace", readme)
        self.assertIn("observatory_paper_trace", readme)
        self.assertIn("service default", readme)
        self.assertIn("generous_layered", readme)
        self.assertIn("legacy run artifacts", readme.lower())
        self.assertIn("Demo Readiness Check", readme)
        self.assertIn("demo_health_check.py --dataset icsi", readme)
        self.assertIn("/api/demo/health?dataset=icsi", readme)


if __name__ == "__main__":
    unittest.main()
