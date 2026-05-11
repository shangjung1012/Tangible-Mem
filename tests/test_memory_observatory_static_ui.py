from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class MemoryObservatoryStaticUiTests(unittest.TestCase):
    def test_retrieval_trace_describes_l1_seed_search_modes(self) -> None:
        html = (REPO_ROOT / "memory_observatory" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn("Hybrid L1 seed search (lexical + semantic when available)", html)
        self.assertIn("Lexical L1 seed search (offline)", html)
        self.assertIn("Semantic L1 seed search (embedding API)", html)
        self.assertIn("L2 / child-L2 / L3 expansion is always layered", html)
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

    def test_retrieval_trace_uses_demo_safe_budget_without_debug_in_prompt(self) -> None:
        html = (REPO_ROOT / "memory_observatory" / "static" / "index.html").read_text(encoding="utf-8")
        js = (REPO_ROOT / "memory_observatory" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("show debug panel", html)
        self.assertIn('const budgetProfile = "observatory_trace"', js)
        self.assertIn("budget_profile=${budgetProfile}", js)
        self.assertIn("include_debug=false", js)
        self.assertIn("budget profile: ${budgetProfile}", js)

    def test_readme_documents_current_trace_and_experiment_defaults(self) -> None:
        readme = (REPO_ROOT / "memory_observatory" / "README.md").read_text(encoding="utf-8")

        self.assertIn("UI Retrieval Trace demo profile", readme)
        self.assertIn("observatory_trace", readme)
        self.assertIn("service default", readme)
        self.assertIn("generous_layered", readme)
        self.assertIn("legacy run artifacts", readme.lower())


if __name__ == "__main__":
    unittest.main()
