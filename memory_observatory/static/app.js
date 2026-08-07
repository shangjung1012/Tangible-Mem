const $ = (sel) => document.querySelector(sel);

const el = (tag, attrs = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "value") node.value = value;
    else if (key === "checked") node.checked = Boolean(value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
};

const api = async (url, opts) => {
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  const type = res.headers.get("content-type") || "";
  return type.includes("json") ? res.json() : res.text();
};

const preview = (text, n = 220) => {
  const value = String(text || "");
  return value.length > n ? `${value.slice(0, n)}...` : value;
};

const fmtNumber = (value, digits = 2) => {
  const num = Number(value || 0);
  return Number.isFinite(num) ? num.toFixed(digits) : "0.00";
};

const tag = (text, cls = "") => el("span", { class: `tag ${cls}`, text });
const DEMO_TRACE_QUERY = "What context about delay-and-sum beamforming and close microphones should carry over to later audio processing discussions?";
const GRACE_DEMO_TRACE_QUERY = "Why did we split transcripts into segments and idea units, and how did that approach evolve?";

function currentDemoQuery() {
  return selectedDataset === "icsi" ? DEMO_TRACE_QUERY : GRACE_DEMO_TRACE_QUERY;
}

function card(title, body, tags = []) {
  return el("div", { class: "card" }, [
    el("div", { class: "label", text: title }),
    el("div", { class: "value", text: body }),
    el("div", {}, tags.map((t) => tag(t.text || t, t.class || ""))),
  ]);
}

function compactMetric(value, digits = 3) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "0.000";
  return num.toFixed(digits);
}

function renderResultCell(value, emphasis = false) {
  return el("td", { class: emphasis ? "result-emphasis" : "", text: String(value) });
}

function loadIcsiScaleResult(data) {
  const evalSummary = data.evaluation_summary || {};
  const surface = data.topic_surface_summary || {};
  const full = evalSummary.full_context || {};
  const rag = evalSummary.rag || {};
  const layered = evalSummary.layered || {};
  const tokenPct = evalSummary.layered_full_context_token_pct || 0;
  const example = evalSummary.example_query || {};
  const corpusLabel = `${data.meeting_count || "large"}-meeting ICSI BMR corpus`;
  return el("div", { class: "icsi-dashboard" }, [
    el("div", { class: "icsi-claim-panel" }, [
      el("div", {}, [
        el("div", { class: "label", text: "Evidence-grounded held-out evaluation" }),
        el("h2", { text: "Layered Memory retrieves more expected evidence in this diagnostic" }),
        el("p", {
          text: `On the ${corpusLabel}, Layered Memory retrieves ${compactMetric(layered.recall)} expected L1 evidence recall versus ${compactMetric(rag.recall)} for RAG top-20, while using about ${compactMetric(tokenPct, 1)}% of Full Context tokens.`,
        }),
      ]),
      el("div", { class: "icsi-claim-metrics" }, [
        card("Layered recall", compactMetric(layered.recall), [{ text: "L1 evidence", class: "feedback" }]),
        card("RAG recall", compactMetric(rag.recall), [{ text: "top-20 chunks", class: "rag" }]),
        card("Full Context", `${full.tokens_label || "575k"} tokens`, [{ text: "all L1", class: "warn" }]),
        card("Layered cost", `${layered.tokens_label || "7.4k"} tokens`, [{ text: "focused context", class: "l2" }]),
      ]),
    ]),
    el("div", { class: "icsi-result-grid" }, [
      el("div", { class: "panel icsi-result-table-panel" }, [
        el("h2", { text: "Scale Result" }),
        el("table", { class: "result-table" }, [
          el("thead", {}, [
            el("tr", {}, [
              el("th", { text: "System" }),
              el("th", { text: "Recall" }),
              el("th", { text: "Context Tokens" }),
            ]),
          ]),
          el("tbody", {}, [
            el("tr", {}, [
              renderResultCell("Full Context"),
              renderResultCell(compactMetric(full.recall)),
              renderResultCell(full.tokens_label || "575k"),
            ]),
            el("tr", {}, [
              renderResultCell("RAG top-20"),
              renderResultCell(compactMetric(rag.recall)),
              renderResultCell(rag.tokens_label || "2.4k"),
            ]),
            el("tr", { class: "layered-row" }, [
              renderResultCell("Layered Memory", true),
              renderResultCell(compactMetric(layered.recall), true),
              renderResultCell(layered.tokens_label || "7.4k", true),
            ]),
          ]),
        ]),
        el("p", { class: "muted", text: "Full Context is strongest on recall but costly at large scale. RAG is cheap but loses expected evidence. Layered Memory keeps the trace focused while preserving more evidence." }),
      ]),
      el("div", { class: "panel icsi-topic-surface" }, [
        el("h2", { text: "L2/L3 Surface" }),
        el("div", { class: "cards mini-cards" }, [
          card("+topic tokens", `+${Math.round(Number(surface.extra_tokens || 0))}`, [{ text: "small overhead", class: "feedback" }]),
          card("L2 hit", compactMetric(surface.l2_hit || 0, 2), [{ text: "topic labels visible", class: "l2" }]),
          card("L3 hit", compactMetric(surface.l3_hit || 0, 2), [{ text: "family labels visible", class: "l3" }]),
        ]),
        el("p", {
          text: "The topic surface is not a replacement for evidence. It is a low-token navigation layer that helps a reviewer see why the selected L1 evidence belongs together.",
        }),
      ]),
      el("div", { class: "panel icsi-evidence-trace" }, [
        el("h2", { text: "Evidence Trace Example" }),
        el("div", { class: "label", text: example.query_id || "held-out query" }),
        el("p", { text: example.query || "Select ICSI to inspect held-out evidence retrieval at corpus scale." }),
        keyValueRows([
          { label: "Full Context recall", value: compactMetric(example.strategies?.full_context_l1?.expected_l1_recall ?? full.recall) },
          { label: "RAG recall", value: compactMetric(example.strategies?.rag_l1_lexical?.expected_l1_recall ?? rag.recall) },
          { label: "Layered recall", value: compactMetric(example.strategies?.optimization_v2_layered?.expected_l1_recall ?? layered.recall) },
          { label: "Expected L1", value: (example.expected_obj_ids || []).join(", ") },
        ]),
      ]),
    ]),
  ]);
}

const STRATEGY_LABELS = {
  full_context: "Full context",
  rag_baseline: "RAG",
  layered_memory: "Layered memory",
};

let currentRunQueries = [];
let selectedQueryId = "";
let selectedDataset = localStorage.getItem("observatoryDataset") || "icsi";
let availableDatasets = [];
let demoAuditBaselineTrace = null;

function apiWithDataset(path) {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}dataset=${encodeURIComponent(selectedDataset)}`;
}

function datasetMeta() {
  return availableDatasets.find((item) => item.dataset_id === selectedDataset) || {};
}

function formatMetricValue(value, kind = "number") {
  const num = Number(value);
  if (!Number.isFinite(num)) return "0";
  if (kind === "ms") {
    return num >= 1000 ? `${(num / 1000).toFixed(2)}s` : `${Math.round(num)}ms`;
  }
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(num);
}

function metricSummaryCard(title, values, kind = "number") {
  const entries = Object.entries(values || {});
  return el("div", { class: "card metric-card" }, [
    el("div", { class: "label", text: title }),
    el("div", { class: "metric-map" }, entries.map(([key, value]) =>
      el("div", { class: "metric-row" }, [
        el("span", { class: "metric-name", title: key, text: STRATEGY_LABELS[key] || key }),
        el("span", { class: "metric-number", text: formatMetricValue(value, kind) }),
      ])
    )),
  ]);
}

function keyValueRows(rows) {
  const filtered = (rows || []).filter((row) => row && row.value !== undefined && row.value !== null && row.value !== "");
  if (!filtered.length) return el("p", { class: "muted", text: "No data available." });
  return el("div", { class: "kv-list" }, filtered.map((row) =>
    el("div", { class: "kv-row" }, [
      el("span", { class: "kv-key", text: row.label }),
      el("span", { class: "kv-value", text: String(row.value) }),
    ])
  ));
}

function topicLinkValue(link, labelKey, idKey) {
  return link[labelKey] || link[idKey] || "";
}

function renderTopicLinkBlock(topicLink) {
  const link = topicLink || {};
  const l2 = topicLinkValue(link, "l2_label", "l2_id");
  const childL2 = topicLinkValue(link, "child_l2_label", "child_l2_id");
  const parentL3 = topicLinkValue(link, "parent_l3_label", "parent_l3_id");
  const path = [
    parentL3 ? { label: "L3 family", value: parentL3, class: "l3" } : null,
    l2 ? { label: childL2 ? "Source L2" : "L2 topic", value: l2, class: "l2" } : null,
    childL2 ? { label: "Assigned child L2", value: childL2, class: "l2" } : null,
  ].filter(Boolean);
  const confidence = link.confidence !== undefined ? fmtNumber(link.confidence) : "";
  const assignmentReason = link.assignment_reason || link.l3_assignment_reason || "";

  if (!path.length) {
    return el("div", { class: "subpanel topic-link-panel" }, [
      el("h3", { text: "Topic Links" }),
      el("p", { class: "muted", text: "This L1 object is not linked to an L2/L3 topic yet." }),
    ]);
  }

  return el("div", { class: "subpanel" }, [
    el("h3", { text: "Topic Links" }),
    el("div", { class: "topic-link-path" }, path.map((item) =>
      el("div", { class: `topic-link-step ${item.class}` }, [
        el("span", { class: "topic-link-step-label", text: item.label }),
        el("strong", { text: item.value }),
      ])
    )),
    el("div", { class: "topic-link-meta" }, [
      confidence ? tag(`confidence ${confidence}`, "feedback") : null,
      assignmentReason ? el("p", { text: assignmentReason }) : null,
    ]),
    el("details", { class: "topic-link-debug" }, [
      el("summary", { text: "Technical IDs" }),
      keyValueRows([
        { label: "L2 ID", value: link.l2_id },
        { label: "Child L2 ID", value: link.child_l2_id },
        { label: "Parent L3 ID", value: link.parent_l3_id },
        { label: "L3 score", value: link.l3_assignment_score !== undefined ? fmtNumber(link.l3_assignment_score) : "" },
      ]),
    ]),
  ]);
}

function demoTopicDescription(label) {
  const value = String(label || "").toLowerCase();
  if (value.includes("audio")) return "How audio capture, channels, filtering, and signal processing become durable meeting context.";
  if (value.includes("annotation") || value.includes("transcription")) return "How annotation and transcription workflow decisions are preserved as inspectable topic memory.";
  if (value.includes("asr") || value.includes("speech recognition")) return "How speech-recognition modeling context carries across BMR meetings.";
  if (value.includes("corpus") || value.includes("data")) return "How corpus construction and data-management decisions accumulate over time.";
  if (value.includes("project") || value.includes("agenda")) return "How planning and meeting-management context remains visible without becoming factual evidence.";
  if (value.includes("fixed") || value.includes("dynamic")) return "How much transcript text should be grouped before extraction.";
  if (value.includes("generation")) return "How transcript windows become concrete idea-unit candidates.";
  if (value.includes("classification")) return "How candidate units are typed before entering memory.";
  if (value.includes("granularity")) return "How fine-grained an idea unit should be.";
  if (value.includes("definition")) return "What separates a segment from an idea unit.";
  if (value.includes("window") || value.includes("boundary")) return "How coherent discussion boundaries are selected.";
  if (value.includes("evidence")) return "How topic memory remains grounded in transcript evidence.";
  return "Durable child topic state built from linked L1 evidence.";
}

function findDemoFamily(topics) {
  const families = (topics || {}).l3_nodes || [];
  if (selectedDataset === "icsi") {
    return families.find((item) => {
      const haystack = `${item.l3_id || ""} ${item.label || ""}`.toLowerCase();
      return haystack.includes("audio acquisition") || haystack.includes("signal processing") || haystack.includes("audio");
    }) || families[0] || {};
  }
  return families.find((item) => {
    const haystack = `${item.l3_id || ""} ${item.label || ""}`.toLowerCase();
    return haystack.includes("transcript") || haystack.includes("idea");
  }) || families[0] || {};
}

function renderDemoChildTopic(child) {
  return el("div", { class: "demo-child-topic" }, [
    el("strong", { text: child.label || child.l2_id || "child L2 topic" }),
    el("span", { text: `${child.event_count || 0} L1 events` }),
    el("p", { text: demoTopicDescription(child.label || child.l2_id) }),
  ]);
}

function renderDemoEvidence(seed) {
  return el("div", { class: "demo-evidence-card" }, [
    el("div", { class: "demo-card-top" }, [
      tag(seed.meeting_id || "meeting", "l1"),
      el("strong", { text: seed.obj_id || "" }),
    ]),
    el("div", { class: "label", text: `${seed.type || "memory"} | score ${fmtNumber(seed.score, 3)} | importance ${fmtNumber(seed.importance)}` }),
    el("p", { text: preview(seed.content || seed.evidence, 210) }),
  ]);
}

function renderDemoTopicContext(topic) {
  const text = topic.evolution_summary || topic.current_state || timelineText(topic.timeline_digest || []);
  return el("div", { class: "demo-topic-context-card" }, [
    el("div", { class: "demo-card-top" }, [
      tag("L2 topic state", "l2"),
      topic.parent_l3_label ? tag(`L3: ${topic.parent_l3_label}`, "l3") : null,
    ]),
    el("strong", { text: topic.label || topic.l2_id || "" }),
    el("div", { class: "label", text: `${topic.selected_event_count || 0} selected event(s), ${topic.omitted_event_count || 0} omitted` }),
    el("p", { text: preview(text, 300) }),
  ]);
}

function renderDemoPromptContext(text) {
  const lines = String(text || "")
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .slice(0, 18);
  return el("pre", { class: "demo-prompt-box", text: lines.join("\n") });
}

function renderDemoComparison() {
  const items = [
    {
      cls: "full",
      title: "Full Context",
      mode: "inject all transcript",
      body: "High token cost; the model must rediscover the relevant history from a large context.",
      tags: ["expensive", "less inspectable"],
    },
    {
      cls: "rag",
      title: "Traditional RAG",
      mode: "top-k chunks",
      body: "Retrieves local snippets, but the topic lifecycle can remain fragmented across meetings.",
      tags: ["cheap", "fragmented"],
    },
    {
      cls: "layered",
      title: "Layered Memory",
      mode: "L1 evidence + L2 evolution + L3 navigation",
      body: "Starts from source-grounded evidence, then adds topic state and family navigation.",
      tags: ["evidence-first", "evolution-aware"],
    },
  ];
  return el("div", { class: "demo-comparison-grid" }, items.map((item) =>
    el("div", { class: `demo-comparison-card ${item.cls}` }, [
      el("h3", { text: item.title }),
      el("strong", { text: item.mode }),
      el("p", { text: item.body }),
      el("div", { class: "tag-row" }, item.tags.map((value) => tag(value, item.cls === "layered" ? "feedback" : item.cls === "rag" ? "rag" : "warn"))),
    ])
  ));
}

function renderDemoHealth(health) {
  const target = $("#demoHealth");
  if (!target) return;
  const status = health.status || "warn";
  const checks = health.checks || [];
  target.className = `demo-health-card ${status}`;
  target.replaceChildren(
    el("div", { class: "demo-health-head" }, [
      el("div", {}, [
        el("div", { class: "demo-eyebrow", text: "Demo readiness" }),
        el("h2", { text: status === "pass" ? "ICSI demo artifacts are ready" : "ICSI demo needs attention" }),
        el("p", { text: `Backend: ${health.resolved_backend || "unknown"} | Dataset: ${health.dataset_label || health.dataset || "unknown"}` }),
      ]),
      tag(status.toUpperCase(), status === "pass" ? "feedback" : status === "warn" ? "warn" : "error"),
    ]),
    el("div", { class: "health-check-grid" }, checks.map((check) =>
      el("div", { class: `health-check ${check.status || "warn"}` }, [
        el("strong", { text: healthCheckLabel(check.name) }),
        el("span", { text: String(check.value ?? "") }),
        el("p", { title: check.detail || "", text: preview(check.detail || "", 96) }),
      ])
    )),
  );
}

function healthCheckLabel(name) {
  const labels = {
    dataset_registered: "dataset",
    share_mem_root_exists: "L1 source",
    l2_view_exists: "L2 runtime view",
    l3_view_exists: "L3 runtime view",
    demo_trace_runs: "trace execution",
    demo_trace_has_l1: "L1 seeds",
    demo_trace_has_l2: "L2 context",
    demo_trace_has_l3: "L3 navigation",
    demo_trace_has_prompt: "prompt context",
  };
  return labels[name] || name || "check";
}

function selectDemoEvidenceSeeds(seeds) {
  const preferredMeetings = selectedDataset === "icsi" ? ["Bmr001", "Bmr002", "Bmr005"] : ["0422", "0429", "0506"];
  const selected = [];
  for (const meetingId of preferredMeetings) {
    const found = seeds.find((seed) => seed.meeting_id === meetingId && !selected.includes(seed));
    if (found) selected.push(found);
  }
  for (const seed of seeds) {
    if (selected.length >= 3) break;
    if (!selected.includes(seed)) selected.push(seed);
  }
  return selected;
}

function renderLayeredEvidenceGraph(family, seeds, contexts, siblingLabels) {
  const selectedSeeds = selectDemoEvidenceSeeds(seeds);
  const context = contexts[0] || {};
  const contextText = context.evolution_summary || context.current_state || timelineText(context.timeline_digest || []);
  const relatedTopics = siblingLabels.slice(0, 3).map((child) => child.label || child.l2_id).filter(Boolean);
  const evidenceMeetingCount = new Set(selectedSeeds.map((seed) => seed.meeting_id).filter(Boolean)).size;
  const queryNodeTitle = selectedDataset === "icsi"
    ? "Beamforming and close microphones"
    : "Transcript segments and idea units";
  return el("section", { class: "demo-section layered-memory-visual" }, [
    el("div", { class: "layered-graph-header" }, [
      el("div", {}, [
        el("div", { class: "demo-eyebrow", text: "Layered evidence graph" }),
        el("h2", { text: "Layered retrieval path" }),
        el("p", { text: "Source evidence, evolving topic state, and wider navigation remain visibly distinct." }),
      ]),
      el("div", { class: "memory-layer-legend", "aria-label": "Memory layer legend" }, [
        el("span", { class: "legend-item l1", text: "L1  Evidence" }),
        el("span", { class: "legend-item l2", text: "L2  Evolution" }),
        el("span", { class: "legend-item l3", text: "L3  Navigation" }),
      ]),
    ]),
    el("div", { class: "layered-evidence-graph" }, [
      el("article", { class: "memory-graph-node query-node" }, [
        el("span", { class: "graph-stage", text: "Question" }),
        el("h3", { text: queryNodeTitle }),
        el("p", { text: "What should carry forward from earlier meetings?" }),
      ]),
      el("div", { class: "graph-connector", "aria-hidden": "true" }),
      el("article", { class: "memory-graph-node l1-node" }, [
        el("div", { class: "graph-node-head" }, [
          el("span", { class: "graph-stage", text: "1  Evidence seeds" }),
          el("strong", { text: `${selectedSeeds.length} objects / ${evidenceMeetingCount} meeting${evidenceMeetingCount === 1 ? "" : "s"}` }),
        ]),
        el("div", { class: "graph-evidence-stack" }, selectedSeeds.map((seed) =>
          el("div", { class: "graph-evidence-row" }, [
            el("div", { class: "graph-evidence-meta" }, [
              tag(seed.meeting_id || "meeting", "l1"),
              el("b", { text: seed.obj_id || "" }),
            ]),
            el("p", { text: preview(seed.content || seed.evidence, 118) }),
          ])
        )),
        el("div", { class: "graph-contribution", text: "Facts from L1" }),
      ]),
      el("div", { class: "graph-connector", "aria-hidden": "true" }),
      el("article", { class: "memory-graph-node l2-node" }, [
        el("span", { class: "graph-stage", text: "2  Topic state" }),
        el("h3", { text: context.label || "audio processing" }),
        el("p", { text: preview(contextText, 260) }),
        el("div", { class: "graph-metrics" }, [
          tag(`${context.selected_event_count || 0} selected`, "l2"),
          tag(`${context.omitted_event_count || 0} omitted`, "muted"),
        ]),
        el("div", { class: "graph-contribution", text: "Evolution from L2" }),
      ]),
      el("div", { class: "graph-connector", "aria-hidden": "true" }),
      el("article", { class: "memory-graph-node l3-node" }, [
        el("span", { class: "graph-stage", text: "3  Topic family" }),
        el("h3", { text: family.label || "audio acquisition and signal processing" }),
        el("p", { text: "Related topic states define scope; they are not treated as factual evidence." }),
        el("div", { class: "graph-topic-list" }, relatedTopics.map((topic) => tag(topic, "l2"))),
        el("div", { class: "graph-contribution", text: "Navigation from L3" }),
      ]),
      el("div", { class: "graph-connector", "aria-hidden": "true" }),
      el("article", { class: "memory-graph-node context-node" }, [
        el("span", { class: "graph-stage", text: "Answer input" }),
        el("h3", { text: "Grounded prompt context" }),
        el("div", { class: "context-recipe" }, [
          el("div", {}, [el("b", { text: "Facts" }), el("span", { text: "verbatim L1 evidence" })]),
          el("div", {}, [el("b", { text: "History" }), el("span", { text: "selected L2 evolution" })]),
          el("div", {}, [el("b", { text: "Scope" }), el("span", { text: "L3 family navigation" })]),
        ]),
        el("div", { class: "graph-contribution", text: "Ready for the answer model" }),
      ]),
    ]),
  ]);
}

function auditTopicState(topic) {
  return String(topic?.current_state || topic?.evolution_summary || timelineText(topic?.timeline_digest || []) || "No topic state is available.");
}

function suggestedAuditState(topic, seeds) {
  if (selectedDataset === "icsi" && String(topic?.label || "").toLowerCase().includes("audio")) {
    return "Near-field microphone arrays remain an open signal-processing problem: non-planar wavefronts make simple delay-and-sum beamforming unsuitable, while closer microphone placement was proposed as an alternative direction that still needs validation.";
  }
  const evidence = (seeds || []).slice(0, 2).map((seed) => String(seed.content || seed.evidence || "").trim()).filter(Boolean);
  if (evidence.length) return `The current topic state should foreground this query-relevant evidence: ${evidence.join(" ")}`;
  return auditTopicState(topic);
}

function renderAuditEvidenceSummary(seed) {
  return el("div", { class: "audit-evidence-summary" }, [
    el("div", { class: "audit-evidence-meta" }, [
      tag(seed.meeting_id || "meeting", "l1"),
      el("strong", { text: seed.obj_id || "L1 evidence" }),
    ]),
    el("p", { text: preview(seed.content || seed.evidence, 155) }),
  ]);
}

function renderAuditEvidenceControl(seed, index) {
  const inputId = `auditExclude${index}`;
  return el("label", { class: "audit-evidence-control", for: inputId }, [
    el("input", { id: inputId, type: "checkbox", value: seed.obj_id || "", "data-audit-exclude": "true" }),
    el("span", {}, [
      el("strong", { text: seed.obj_id || "L1 evidence" }),
      el("small", { text: `Exclude from candidate context: ${preview(seed.content || seed.evidence, 96)}` }),
    ]),
  ]);
}

function renderAuditVerifyInitial(topic, seeds) {
  return el("div", { class: "audit-verify-body audit-waiting" }, [
    el("div", { class: "audit-baseline-state" }, [
      el("span", { class: "audit-field-label", text: "Baseline topic state" }),
      el("strong", { text: topic?.label || topic?.l2_id || "L2 topic" }),
      el("p", { text: preview(auditTopicState(topic), 360) }),
    ]),
    el("div", { class: "audit-pending-checks" }, [
      el("div", {}, [el("b", { text: String(seeds.length) }), el("span", { text: "L1 evidence objects currently enter the trace" })]),
      el("div", {}, [el("b", { text: "Pending" }), el("span", { text: "Run the sandbox to rebuild the candidate prompt" })]),
      el("div", {}, [el("b", { text: "Not run" }), el("span", { text: "Answer generation waits for verified Vertex access" })]),
    ]),
  ]);
}

function impactRow(label, before, after, tone = "") {
  return el("div", { class: `audit-impact-row ${tone}` }, [
    el("span", { text: label }),
    el("b", { text: String(before) }),
    el("span", { class: "audit-impact-arrow", text: "to" }),
    el("b", { text: String(after) }),
  ]);
}

function renderAuditDiff(result) {
  const target = $("#auditDiff");
  if (!target) return;
  const rows = result.context_diff || [];
  const truncationNotice = result.context_diff_truncated
    ? el("p", { class: "muted", text: "The visual diff is truncated; the complete candidate context remains available in Retrieval Trace." })
    : null;
  target.replaceChildren(
    el("div", { class: "audit-diff-header" }, [
      el("div", {}, [
        el("span", { class: "audit-field-label", text: "Prompt context diff" }),
        el("h3", { text: "What the answer model would receive differently" }),
      ]),
      el("div", { class: "audit-diff-legend" }, [
        el("span", { class: "remove", text: "Removed" }),
        el("span", { class: "add", text: "Added" }),
      ]),
    ]),
    rows.length
      ? el("div", { class: "audit-context-diff", role: "log", "aria-label": "Baseline and candidate prompt differences" }, rows.map((row) =>
          el("code", { class: `diff-${row.kind || "context"}`, text: row.text || "" })
        ))
      : el("p", { class: "muted", text: "The selected adjustment did not change the formatted prompt context." }),
  );
  if (truncationNotice) target.append(truncationNotice);
  target.hidden = false;
}

function renderAuditVerifyResult(result) {
  const target = $("#auditVerify");
  if (!target) return;
  const impact = result.impact || {};
  const correction = result.correction || {};
  target.replaceChildren(
    el("div", { class: "audit-verify-status" }, [
      el("span", { class: "audit-status-mark", text: "3" }),
      el("div", {}, [
        el("strong", { text: "Candidate context rebuilt" }),
        el("p", { text: "The same query was formatted again with the session correction." }),
      ]),
    ]),
    el("div", { class: "audit-impact-list" }, [
      impactRow("L1 evidence", impact.l1_count_before ?? 0, impact.l1_count_after ?? 0),
      impactRow("Prompt tokens", impact.prompt_tokens_before ?? 0, impact.prompt_tokens_after ?? 0),
      impactRow("Prompt characters", impact.prompt_chars_before ?? 0, impact.prompt_chars_after ?? 0),
    ]),
    correction.corrected_state
      ? el("div", { class: "audit-candidate-state" }, [
          el("span", { class: "audit-field-label", text: "Candidate topic state" }),
          el("p", { text: correction.corrected_state }),
        ])
      : null,
    el("div", { class: "audit-guardrail-list" }, [
      el("div", {}, [tag(impact.raw_evidence_unchanged ? "PASS" : "CHECK", impact.raw_evidence_unchanged ? "feedback" : "warn"), el("span", { text: "Raw L1 evidence unchanged" })]),
      el("div", {}, [tag("SESSION", "l2"), el("span", { text: "Candidate is not persisted" })]),
      el("div", {}, [tag("PENDING", "warn"), el("span", { text: "Answer-level effect not generated yet" })]),
    ]),
  );
  renderAuditDiff(result);
}

async function runDemoAuditPreview(event) {
  event.preventDefault();
  if (!demoAuditBaselineTrace) return;
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const status = $("#auditActionStatus");
  const excludeObjIds = [...form.querySelectorAll("[data-audit-exclude]:checked")].map((input) => input.value).filter(Boolean);
  const payload = {
    query: demoAuditBaselineTrace.query || currentDemoQuery(),
    retrieval_mode: "lexical",
    budget_profile: "observatory_paper_trace",
    correction: {
      target_l2_id: form.elements.target_l2_id.value,
      corrected_state: form.elements.corrected_state.value.trim(),
      reason_code: form.elements.reason_code.value,
      exclude_obj_ids: excludeObjIds,
    },
  };
  submit.disabled = true;
  submit.textContent = "Rebuilding candidate...";
  status.className = "audit-action-status working";
  status.textContent = "Applying the correction to an in-memory copy of the retrieval result.";
  try {
    const result = await api(apiWithDataset("/api/demo/audit-preview"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderAuditVerifyResult(result);
    status.className = "audit-action-status success";
    status.textContent = "Candidate prompt rebuilt. Nothing was written to the source memory.";
  } catch (error) {
    status.className = "audit-action-status error";
    status.textContent = `Could not build the candidate: ${error.message}`;
  } finally {
    submit.disabled = false;
    submit.textContent = "Apply in audit sandbox";
  }
}

function renderDemoAudit(trace) {
  demoAuditBaselineTrace = trace;
  const target = $("#demoAudit");
  if (!target) return;
  const seeds = (trace.l1_evidence_seeds || []).slice(0, 3);
  const topics = (trace.l2_evolution_context || []).filter((topic) => topic?.l2_id).slice(0, 4);
  const primaryTopic = topics[0] || {};
  const suggested = suggestedAuditState(primaryTopic, seeds);
  const targetSelect = el("select", { name: "target_l2_id", "aria-label": "Topic state to challenge" }, topics.map((topic) =>
    el("option", { value: topic.l2_id || "", text: topic.label || topic.l2_id || "L2 topic" })
  ));
  const correctedState = el("textarea", {
    name: "corrected_state",
    rows: "6",
    placeholder: "Describe the topic state that should enter this query's candidate context.",
    "aria-label": "Candidate topic state",
  });
  correctedState.value = suggested;
  const verifyPanel = el("article", { id: "auditVerify", class: "audit-step audit-verify" }, [
    el("div", { class: "audit-step-heading" }, [
      el("span", { class: "audit-step-number", text: "3" }),
      el("div", {}, [el("h2", { text: "Verify the effect" }), el("p", { text: "Compare the rebuilt context before claiming control." })]),
    ]),
    renderAuditVerifyInitial(primaryTopic, trace.l1_evidence_seeds || []),
  ]);
  const form = el("form", { id: "auditChallengeForm", class: "audit-step audit-challenge" }, [
    el("div", { class: "audit-step-heading" }, [
      el("span", { class: "audit-step-number", text: "2" }),
      el("div", {}, [el("h2", { text: "Challenge the memory" }), el("p", { text: "Create a reversible candidate, not a silent overwrite." })]),
    ]),
    el("label", { class: "audit-control-group" }, [
      el("span", { class: "audit-field-label", text: "Topic state to challenge" }),
      targetSelect,
    ]),
    el("label", { class: "audit-control-group" }, [
      el("span", { class: "audit-field-label", text: "Candidate state" }),
      correctedState,
    ]),
    el("fieldset", { class: "audit-exclusion-fieldset" }, [
      el("legend", { text: "Optional evidence exclusions" }),
      ...seeds.map(renderAuditEvidenceControl),
    ]),
    el("label", { class: "audit-control-group" }, [
      el("span", { class: "audit-field-label", text: "Reason" }),
      el("select", { name: "reason_code" }, [
        el("option", { value: "topic_state_not_query_relevant", text: "Topic state is not query-relevant" }),
        el("option", { value: "summary_too_broad", text: "Summary is too broad" }),
        el("option", { value: "stale_topic_state", text: "Topic state is stale" }),
        el("option", { value: "unsupported_evidence", text: "Evidence is unsupported" }),
        el("option", { value: "other", text: "Other" }),
      ]),
    ]),
    el("div", { class: "audit-button-row" }, [
      el("button", { type: "submit", text: "Apply in audit sandbox" }),
      el("button", {
        type: "button",
        class: "secondary",
        text: "Reset candidate",
        onclick: () => renderDemoAudit(demoAuditBaselineTrace),
      }),
    ]),
    el("p", { id: "auditActionStatus", class: "audit-action-status", text: "Session-only preview. Raw memory and runtime artifacts remain locked." }),
  ]);
  form.addEventListener("submit", runDemoAuditPreview);
  target.className = "audit-workspace";
  target.replaceChildren(
    el("div", { class: "audit-workspace-header" }, [
      el("div", {}, [
        el("div", { class: "demo-eyebrow", text: "Closed-loop memory audit" }),
        el("h2", { text: "Inspect, challenge, and verify" }),
        el("p", { text: "A visible trace is not enough. A correction should produce an observable change without altering the source evidence." }),
      ]),
      el("div", { class: "audit-scope" }, [tag("Raw L1 locked", "l1"), tag("Session sandbox", "feedback"), tag("No model call", "l2")]),
    ]),
    el("div", { class: "audit-grid" }, [
      el("article", { class: "audit-step audit-inspect" }, [
        el("div", { class: "audit-step-heading" }, [
          el("span", { class: "audit-step-number", text: "1" }),
          el("div", {}, [el("h2", { text: "Inspect the behavior" }), el("p", { text: "See which facts and topic state entered the baseline." })]),
        ]),
        el("div", { class: "audit-observed-topic" }, [
          el("span", { class: "audit-field-label", text: "Observed topic state" }),
          el("strong", { text: primaryTopic.label || primaryTopic.l2_id || "No L2 topic selected" }),
          el("p", { text: preview(auditTopicState(primaryTopic), 420) }),
        ]),
        el("div", { class: "audit-evidence-list" }, [
          el("span", { class: "audit-field-label", text: "Baseline evidence" }),
          ...seeds.map(renderAuditEvidenceSummary),
        ]),
      ]),
      form,
      verifyPanel,
    ]),
    el("section", { id: "auditDiff", class: "audit-diff-section", hidden: "hidden" }),
  );
}

function renderDemoStory(topics, trace) {
  const family = findDemoFamily(topics);
  const children = (family.child_l2_nodes || []).slice()
    .sort((a, b) => Number(b.event_count || 0) - Number(a.event_count || 0))
    .slice(0, 6);
  const seeds = (trace.l1_evidence_seeds || []).slice(0, 5);
  const dates = [...new Set(seeds.map((seed) => seed.meeting_id).filter(Boolean))];
  const contexts = (trace.l2_evolution_context || []).slice(0, 2);
  const siblingLabels = (((trace.global_topic_map || {}).l3_families || [])[0] || {}).child_l2 || [];
  const target = $("#demoStory");
  if (!target) return;
  target.className = "demo-story";
  target.replaceChildren(
    renderLayeredEvidenceGraph(family, seeds, contexts, siblingLabels),
    el("section", { class: "demo-section demo-topic-section" }, [
      el("div", { class: "demo-section-copy" }, [
        el("div", { class: "demo-eyebrow", text: "1. Memory topic map" }),
        el("h2", { text: "What the system remembers" }),
        el("p", { text: "Persistent L2 topic states are grouped under an L3 navigation family before retrieval begins." }),
        el("div", { class: "demo-family-card" }, [
          el("div", { class: "tag-row" }, [
            tag("L3 topic family", "l3"),
            tag(`${children.length} shown topic nodes`, "l2"),
            tag(`${family.event_count || 0} linked L1`, "l1"),
          ]),
          el("strong", { text: family.label || family.l3_id || "audio acquisition and signal processing" }),
          el("span", { class: "label", text: family.l3_id || "" }),
          el("p", { text: "L3 is navigation context; factual claims still come from linked L1 evidence." }),
        ]),
      ]),
      el("div", { class: "demo-child-grid" }, children.map(renderDemoChildTopic)),
    ]),
    el("section", { class: "demo-section demo-trace-section" }, [
      el("div", { class: "demo-section-copy" }, [
        el("div", { class: "demo-eyebrow", text: "2. Evidence trace" }),
        el("h2", { text: "What this question retrieves" }),
        el("p", { text: trace.query || currentDemoQuery() }),
        el("div", { class: "demo-date-strip" }, [
          el("strong", { text: "L1 evidence path" }),
          el("div", { class: "tag-row" }, dates.map((date) => tag(date, "l1"))),
        ]),
      ]),
      el("div", { class: "demo-trace-grid" }, [
        el("div", { class: "demo-trace-column l1" }, [
          el("h3", { text: "L1 Evidence Seeds" }),
          ...seeds.slice(0, 3).map(renderDemoEvidence),
        ]),
        el("div", { class: "demo-trace-column l2" }, [
          el("h3", { text: "L2 / Child-L2 Evolution Context" }),
          ...contexts.map(renderDemoTopicContext),
          el("div", { class: "demo-sibling-card" }, [
            el("strong", { text: "L3 sibling navigation" }),
            el("p", { text: "Related topic states remain visible without becoming unsupported evidence." }),
            el("div", { class: "tag-row" }, siblingLabels.slice(0, 4).map((child) => tag(child.label || child.l2_id, "l2"))),
          ]),
        ]),
        el("div", { class: "demo-trace-column prompt" }, [
          el("h3", { text: "Formatted Prompt Context" }),
          el("p", { text: "This is the compact context injected to the answer model." }),
          renderDemoPromptContext(trace.formatted_prompt_context),
        ]),
      ]),
    ]),
    el("section", { class: "demo-section demo-compare-section" }, [
      el("div", { class: "demo-section-copy" }, [
        el("div", { class: "demo-eyebrow", text: "3. Strategy comparison" }),
        el("h2", { text: "Why the memory layers matter" }),
        el("p", { text: "Full Context is broad, RAG is local, and Layered Memory is evidence-grounded plus evolution-aware." }),
      ]),
      renderDemoComparison(),
    ]),
  );
}

async function loadDemoStory() {
  const target = $("#demoStory");
  if (!target) return;
  const auditTarget = $("#demoAudit");
  const query = currentDemoQuery();
  if ($("#demoQueryText")) $("#demoQueryText").textContent = query;
  if ($("#demoWorkspaceLabel")) $("#demoWorkspaceLabel").textContent = `${selectedDataset.toUpperCase()} memory control audit`;
  if ($("#demoQueryType")) $("#demoQueryType").textContent = selectedDataset === "icsi" ? "Rationale and carry-over query" : "Rationale and method-evolution query";
  if (auditTarget) {
    auditTarget.className = "audit-workspace loading";
    auditTarget.textContent = "Preparing the audit sandbox...";
  }
  target.className = "demo-story loading";
  target.textContent = "Loading demo trace...";
  const healthTarget = $("#demoHealth");
  if (healthTarget) {
    healthTarget.className = "demo-health-card loading";
    healthTarget.textContent = "Checking demo readiness...";
  }
  try {
    const [topics, trace, health] = await Promise.all([
      api(apiWithDataset("/api/topics/l3")),
      api(`/api/retrieval/trace?dataset=${selectedDataset}&query=${encodeURIComponent(query)}&retrieval_mode=lexical&no_llm=true&include_debug=false&budget_profile=observatory_paper_trace&max_context_chars=0`),
      api(`/api/demo/health?dataset=${selectedDataset}`),
    ]);
    renderDemoHealth(health);
    renderDemoAudit(trace);
    renderDemoStory(topics, trace);
  } catch (error) {
    target.className = "demo-story error";
    target.textContent = `Could not load demo story: ${error.message}`;
    if (healthTarget) {
      healthTarget.className = "demo-health-card fail";
      healthTarget.textContent = `Could not check demo readiness: ${error.message}`;
    }
    if (auditTarget) {
      auditTarget.className = "audit-workspace error";
      auditTarget.textContent = `Could not prepare the audit sandbox: ${error.message}`;
    }
  }
}

function renderFeedbackHistoryBlock(history) {
  const rows = history || [];
  if (!rows.length) {
    return el("div", { class: "subpanel" }, [
      el("h3", { text: "Feedback History" }),
      el("p", { class: "muted", text: "No feedback has been saved for this object." }),
    ]);
  }
  return el("div", { class: "subpanel" }, [
    el("h3", { text: "Feedback History" }),
    ...rows.map((item) => el("div", { class: "feedback-item" }, [
      el("strong", { text: `${fmtNumber(item.canonical_importance)} -> ${fmtNumber(item.effective_importance)}` }),
      el("div", { class: "label", text: `${item.reason_code || "reason not set"} | ${item.created_at_utc || ""}` }),
      item.note ? el("p", { text: item.note }) : null,
    ])),
  ]);
}

function renderCorrectionHistoryBlock(corrections) {
  const summaryRows = corrections?.summary_corrections || [];
  const flags = corrections?.validity_flags || [];
  const topicRows = corrections?.topic_link_reviews || [];
  const rows = [
    ...summaryRows.map((item) => ({
      title: item.corrected_content || "summary correction",
      meta: `${item.reason_code || "summary"} | ${item.created_at_utc || ""}`,
      note: item.note || "Effective summary correction; raw L1 remains unchanged.",
    })),
    ...flags.map((item) => ({
      title: item.flag_type || "validity flag",
      meta: `${item.reason_code || "validity"} | ${item.created_at_utc || ""}`,
      note: item.note || "Validity sidecar for the effective memory view.",
    })),
    ...topicRows.map((item) => ({
      title: `${item.action || "review"} ${item.l2_id || item.l2_label || "topic link"}`,
      meta: `${item.reason_code || "topic_link"} | ${item.created_at_utc || ""}`,
      note: item.note || "Topic-link sidecar; raw L1 remains unchanged.",
    })),
  ];
  if (!rows.length) {
    return el("div", { class: "subpanel" }, [
      el("h3", { text: "Correction Sidecars" }),
      el("p", { class: "muted", text: "No correction sidecars have been saved for this object." }),
    ]);
  }
  return el("div", { class: "subpanel" }, [
    el("h3", { text: "Correction Sidecars" }),
    ...rows.map((item) => el("div", { class: "feedback-item" }, [
      el("strong", { text: item.title }),
      el("div", { class: "label", text: item.meta }),
      item.note ? el("p", { text: item.note }) : null,
    ])),
  ]);
}

function memoryCard(title, meta, body, tags = []) {
  return el("div", { class: "card memory-card" }, [
    el("strong", { text: title || "" }),
    el("div", { class: "label", text: meta || "" }),
    el("p", { text: preview(typeof body === "string" ? body : JSON.stringify(body)) }),
    el("div", {}, tags.map((item) => tag(item.text || item, item.class || item))),
  ]);
}

function section(title, text) {
  return el("div", { class: "panel" }, [el("h2", { text: title }), el("pre", { text })]);
}

function listSection(title, items, render) {
  return el("div", { class: "panel" }, [
    el("h2", { text: title }),
    ...((items || []).map(render)),
  ]);
}

function activateTab(tabId, updateHash = true) {
  const target = document.getElementById(tabId);
  const button = document.querySelector(`.nav[data-tab="${tabId}"]`);
  if (!target || !button) return;
  document.querySelectorAll(".nav,.tab").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  target.classList.add("active");
  if (updateHash) history.replaceState(null, "", `#${tabId}`);
}

document.querySelectorAll(".nav").forEach((button) => {
  button.addEventListener("click", () => activateTab(button.dataset.tab));
});

function syncDatasetSwitch() {
  document.querySelectorAll("[data-dataset]").forEach((button) => {
    button.classList.toggle("active", button.dataset.dataset === selectedDataset);
  });
  document.body.dataset.dataset = selectedDataset;
}

async function loadDatasets() {
  availableDatasets = await api("/api/datasets").catch(() => []);
  if (!availableDatasets.some((item) => item.dataset_id === selectedDataset)) {
    selectedDataset = availableDatasets.some((item) => item.dataset_id === "icsi") ? "icsi" : "grace";
  }
  localStorage.setItem("observatoryDataset", selectedDataset);
  syncDatasetSwitch();
}

async function reloadDatasetViews() {
  selectedMeetingId = "";
  selectedObjectId = "";
  currentTopicId = null;
  await loadOverview();
  await loadDemoStory();
  await loadExplorer();
  await loadTopics();
  await loadFeedback();
}

document.querySelectorAll("[data-dataset]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (button.dataset.dataset === selectedDataset) return;
    selectedDataset = button.dataset.dataset || "grace";
    localStorage.setItem("observatoryDataset", selectedDataset);
    syncDatasetSwitch();
    await reloadDatasetViews();
  });
});

async function loadOverview() {
  const data = await api(apiWithDataset("/api/overview"));
  const isIcsi = data.dataset_id === "icsi";
  $("#overviewTitle").textContent = isIcsi ? "ICSI Large-Corpus Memory Observatory" : "Evidence-first layered memory";
  $("#overviewLede").textContent = isIcsi
    ? `A presentation-focused view of ${data.meeting_count || "large-scale"} ICSI BMR meetings. It compares Full Context, RAG, and Layered Memory on evidence-grounded held-out queries, then shows how L1 evidence is organized into L2/L3 topic surfaces.`
    : "This system does not directly RAG over transcripts. It first extracts traceable L1 evidence objects, organizes them into L2 / child-L2 topic context, and uses L3 topic families as navigation. Answers should be grounded by L1 evidence, with L2/L3 providing cross-meeting evolution.";
  $("#overviewFlow").style.display = isIcsi ? "none" : "flex";
  $("#icsiScaleResult").replaceChildren(...(isIcsi ? [loadIcsiScaleResult(data)] : []));
  const fields = [
    "meeting_count", "l1_object_count", "l2_topic_count", "linked_l1_count",
    "unlinked_l1_count", "materialized_l3_count", "child_l2_count",
    "l3_assigned_l1_count", "l3_unassigned_l1_count", "duplicate_assignment_count",
    "invalid_l3_index_count", "retrieval_eval_query_count", "retrieval_eval_run_count",
  ];
  $("#overviewCards").replaceChildren(...(isIcsi ? [] : fields.map((key) => card(key, String(data[key] ?? 0)))));
}

function traceModeLabel(mode) {
  if (mode === "hybrid") return "L1 search: hybrid (lexical + semantic when available)";
  if (mode === "semantic") return "L1 search: semantic (embedding API)";
  return "L1 search: lexical (offline)";
}

function renderTraceRouter(data) {
  const router = data.router_result || {};
  const targets = Array.isArray(router.targets) ? router.targets : [];
  const hasLong = targets.includes("long_term");
  return el("div", { class: "panel trace-router" }, [
    el("h2", { text: "Router / Memory Layers" }),
    el("div", { class: "cards mini-cards" }, [
      card("Long-term memory", hasLong ? "ON" : "OFF", [
        { text: hasLong ? "evidence + topic context" : "not needed", class: hasLong ? "l2" : "" },
      ]),
    ]),
    keyValueRows([
      { label: "strategy", value: router.strategy },
      { label: "reason", value: router.reason },
      { label: "confidence", value: router.confidence },
    ]),
  ]);
}

function syncTracePlannerControl() {
  const noLlm = $("#traceNoLlm").checked;
  const tracePlannerModel = $("#tracePlannerModel");
  const hint = $("#tracePlannerHint");
  tracePlannerModel.disabled = noLlm;
  if (noLlm) {
    tracePlannerModel.value = "";
    tracePlannerModel.placeholder = "heuristic planner";
    hint.textContent = "Heuristic planner: no model call.";
  } else {
    if (!tracePlannerModel.value) tracePlannerModel.value = "gemini-2.5-pro";
    tracePlannerModel.placeholder = "gemini-2.5-pro";
    hint.textContent = "LLM planner enabled. This model is used only for recall planning; answer/recall model remains separate.";
  }
}

function renderTraceL2Card(item) {
  const node = memoryCard(
    item.l2_id,
    `${item.label || ""} | selected ${item.selected_event_count || 0} | omitted ${item.omitted_event_count || 0}`,
    timelineText(item.timeline_digest) || item.current_state,
    ["l2", "click for L2 detail"],
  );
  node.classList.add("clickable-card");
  node.addEventListener("click", () => loadTraceL2Detail(item));
  return node;
}

function renderTraceGlobalTopicMap(map) {
  const topicMap = map || {};
  const families = topicMap.l3_families || [];
  const unpromoted = topicMap.l2_topics || [];
  return el("div", { class: "panel trace-topic-map" }, [
    el("h2", { text: "Global Topic Map" }),
    el("p", {
      class: "muted",
      text: topicMap.note || "Navigation context only; do not use as standalone factual evidence.",
    }),
    ...families.map((family) => el("div", { class: "subpanel" }, [
      el("div", { class: "tag-row" }, [
        tag("L3", "l3"),
        tag(`${family.event_count || 0} L1`, ""),
        family.focused ? tag("query focused", "feedback") : null,
      ]),
      el("h3", { text: family.label || family.l3_id || "L3 topic family" }),
      el("div", { class: "label", text: family.l3_id || "" }),
      el("div", { class: "tag-row" }, (family.child_l2 || []).map((child) =>
        tag(`${child.label || child.l2_id} (${child.event_count || 0})`, "l2")
      )),
    ])),
    unpromoted.length ? el("div", { class: "subpanel" }, [
      el("h3", { text: "Unpromoted L2 topics" }),
      el("div", { class: "tag-row" }, unpromoted.map((topic) =>
        tag(`${topic.label || topic.l2_id} (${topic.event_count || 0})`, "l2")
      )),
    ]) : null,
  ]);
}

function renderTraceL3Navigation(items) {
  const rows = items || [];
  return el("div", { class: "panel trace-l3-navigation" }, [
    el("h2", { text: "Parent L3 Navigation" }),
    rows.length
      ? el("div", { class: "cards mini-cards" }, rows.map((item) =>
        memoryCard(item.l3_id, item.label || "", "Topic family selected from L1 seed obj_id links.", ["l3"])
      ))
      : el("p", { class: "muted", text: "No parent L3 selected for this trace." }),
  ]);
}

function renderTraceDebugPanel(data) {
  const metrics = data.metrics || {};
  const debug = data.retrieval_debug || {};
  return el("div", { class: "panel trace-debug" }, [
    el("h2", { text: "Retrieval Debug" }),
    keyValueRows([
      { label: "selected L1", value: metrics.selected_l1_count },
      { label: "selected L2", value: metrics.selected_l2_count },
      { label: "selected child L2", value: metrics.selected_child_l2_count },
      { label: "selected L3", value: metrics.selected_l3_count },
      { label: "omitted events", value: metrics.omitted_event_count },
      { label: "context chars", value: metrics.context_char_count },
      { label: "estimated tokens", value: metrics.estimated_context_tokens },
      { label: "prompt budget", value: metrics.prompt_budget_pass ? "pass" : "fail" },
      { label: "hybrid lexical hits", value: debug.hybrid_lexical_count },
      { label: "hybrid semantic hits", value: debug.hybrid_semantic_count },
      { label: "semantic used", value: debug.hybrid_semantic_used === undefined ? "" : String(debug.hybrid_semantic_used) },
    ]),
  ]);
}

function renderTraceTimeline(title, timeline, limit = 80) {
  const rows = (Array.isArray(timeline) ? timeline : []).slice(0, limit);
  if (!rows.length) {
    return el("div", { class: "subpanel" }, [
      el("h3", { text: title }),
      el("p", { class: "muted", text: "No timeline events in this view." }),
    ]);
  }
  return el("div", { class: "subpanel" }, [
    el("h3", { text: title }),
    el("div", { class: "timeline" }, rows.map((event) => el("div", { class: "timeline-event" }, [
      el("div", { class: "timeline-dot" }),
      el("div", {}, [
        el("strong", { text: `${event.meeting_date || event.meeting_id || ""} | ${event.obj_id || ""}` }),
        el("p", { text: preview(event.summary || event.content || "", 520) }),
      ]),
    ]))),
  ]);
}

async function loadTraceL2Detail(traceItem) {
  const target = $("#traceL2Detail");
  if (!target || !traceItem || !traceItem.l2_id) return;
  target.replaceChildren(el("p", { class: "muted", text: "Loading L2 topic detail..." }));
  const fullTopic = await api(apiWithDataset(`/api/topics/l2/${encodeURIComponent(traceItem.l2_id)}`));
  const matched = traceItem.matched_l1_ids || [];
  const linkedObjects = fullTopic.linked_l1_objects || [];
  target.replaceChildren(
    el("div", { class: "trace-l2-detail-header" }, [
      el("div", {}, [
        el("h2", { text: traceItem.label || fullTopic.label || traceItem.l2_id }),
        el("div", { class: "label", text: traceItem.l2_id }),
      ]),
      el("div", { class: "tag-row" }, [
        tag("Selected in this trace", "l2"),
        fullTopic.parent_l3_id ? tag(`parent ${fullTopic.parent_l3_id}`, "l3") : tag("unpromoted L2", ""),
      ]),
    ]),
    el("div", { class: "cards mini-cards" }, [
      card("matched_l1", String(matched.length)),
      card("selected_events", String(traceItem.selected_event_count || 0)),
      card("omitted_events", String(traceItem.omitted_event_count || 0)),
      card("full_l2_linked_l1", String(linkedObjects.length || fullTopic.event_count || 0)),
    ]),
    renderKeyValueBlock("Selected in this trace", [
      `matched L1: ${matched.length ? matched.join(", ") : "none"}`,
      `prompt slice: ${traceItem.selected_event_count || 0} event(s) shown, ${traceItem.omitted_event_count || 0} omitted`,
      "This is the compact context actually injected into the trace prompt.",
    ].join("\n")),
    renderTraceTimeline("Selected timeline slice", traceItem.timeline_digest || [], 20),
    renderKeyValueBlock("Full L2 topic", fullTopic.current_state || fullTopic.split_reason || "No full topic state available."),
    renderTraceTimeline("Full L2 timeline", fullTopic.timeline_digest || [], 80),
    el("div", { class: "subpanel" }, [
      el("h3", { text: `Linked L1 objects (${linkedObjects.length})` }),
      ...linkedObjects.slice(0, 30).map((obj) => el("div", { class: "evidence-card l1-evidence" }, [
        el("strong", { text: obj.obj_id || "" }),
        el("div", { class: "label", text: `${obj.meeting_id || ""} | ${obj.type || ""} | imp ${fmtNumber(obj.effective_importance ?? obj.importance)}` }),
        el("p", { text: preview(obj.content || obj.content_preview, 300) }),
      ])),
      linkedObjects.length > 30 ? el("p", { class: "muted", text: `${linkedObjects.length - 30} more linked L1 objects omitted from the detail panel.` }) : null,
    ]),
  );
  target.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function runTrace() {
  syncTracePlannerControl();
  const q = encodeURIComponent($("#traceQuery").value);
  const mode = $("#traceMode").value;
  const noLlm = $("#traceNoLlm").checked;
  const debug = $("#traceDebug").checked;
  const plannerModel = encodeURIComponent(noLlm ? "" : ($("#tracePlannerModel").value || ""));
  const budgetProfile = $("#traceBudgetProfile").value || "observatory_trace";
  const maxContextChars = budgetProfile === "observatory_paper_trace" ? 0 : 16000;
  const data = await api(`/api/retrieval/trace?dataset=${selectedDataset}&query=${q}&retrieval_mode=${mode}&no_llm=${noLlm}&include_debug=false&planner_model=${plannerModel}&budget_profile=${budgetProfile}&max_context_chars=${maxContextChars}`);
  const out = $("#traceOutput");
  const planTags = [
    { text: traceModeLabel(data.retrieval_mode) },
    { text: "L2/L3 expansion: layered" },
    data.use_llm_planner
      ? { text: `planner model: ${data.planner_model || ""}` }
      : { text: "Heuristic planner: no model call" },
    { text: `recall/gate model: ${data.answer_model || ""}` },
    { text: `budget profile: ${budgetProfile}` },
    { text: `prompt budget: ${data.metrics.prompt_budget_pass ? "pass" : "fail"}`, class: data.metrics.prompt_budget_pass ? "feedback" : "warn" },
    { text: `omitted events: ${data.metrics.omitted_event_count || 0}` },
  ];
  const traceSections = [
    card("Query / Plan", `${data.metrics.selected_l1_count} L1, ${data.metrics.selected_l2_count} L2, ${data.metrics.selected_child_l2_count} child L2`, [
      ...planTags,
    ]),
    renderTraceRouter(data),
    listSection("L1 Evidence Seeds", data.l1_evidence_seeds, (item) =>
      memoryCard(item.obj_id, `${item.meeting_id} | ${item.type} | score ${item.score}`, item.content, ["l1"])),
    listSection("L2 / Child-L2 Evolution Context", data.l2_evolution_context, (item) =>
      renderTraceL2Card(item)),
    renderTraceL3Navigation(data.l3_navigation),
    renderTraceGlobalTopicMap(data.global_topic_map),
    el("div", { id: "traceL2Detail", class: "panel trace-l2-detail" }, [
      el("h2", { text: "L2 Detail" }),
      el("p", { class: "muted", text: "Click an L2 / child-L2 card above to see what this trace selected and what the full L2 contains." }),
    ]),
    section("Formatted Prompt Context", data.formatted_prompt_context),
    debug ? renderTraceDebugPanel(data) : null,
  ].filter(Boolean);
  out.replaceChildren(...traceSections);
}

async function loadExplorer() {
  currentMeetings = await api(apiWithDataset("/api/meetings"));
  renderMeetings();
  if (currentMeetings[0]) await loadObjects(currentMeetings[0].meeting_id);
}

let currentMeetings = [];
let currentObjects = [];
let selectedMeetingId = "";
let selectedObjectId = "";

function renderMeetings() {
  $("#meetingList").replaceChildren(...currentMeetings.map((m) => {
    const node = memoryCard(m.meeting_id, `${m.meeting_date} | ${m.object_count} objects`, `${m.high_importance_count} high importance`, []);
    node.classList.add("clickable-card", "explorer-meeting-card");
    if (m.meeting_id === selectedMeetingId) node.classList.add("active");
    node.addEventListener("click", () => loadObjects(m.meeting_id));
    return node;
  }));
}

async function loadObjects(meetingId) {
  selectedMeetingId = meetingId;
  selectedObjectId = "";
  currentObjects = await api(apiWithDataset(`/api/meetings/${meetingId}/objects`));
  const types = [...new Set(currentObjects.map((obj) => obj.type).filter(Boolean))].sort();
  $("#objectTypeFilter").replaceChildren(
    el("option", { value: "", text: "all types" }),
    ...types.map((t) => el("option", { value: t, text: t })),
  );
  renderMeetings();
  renderObjects();
  if (currentObjects[0]) {
    await loadObjectDetail(currentObjects[0].obj_id);
  } else {
    $("#objectDetail").replaceChildren(el("p", { class: "muted", text: "No L1 objects match this meeting." }));
  }
}

function renderObjects() {
  const type = $("#objectTypeFilter").value;
  const link = $("#objectLinkFilter").value;
  const minImp = Number($("#importanceFilter").value || 0);
  const objects = currentObjects.filter((obj) => {
    if (type && obj.type !== type) return false;
    if (minImp && Number(obj.effective_importance || 0) < minImp) return false;
    if (link === "linked" && !(obj.topic_link || {}).l2_id) return false;
    if (link === "unlinked" && (obj.topic_link || {}).l2_id) return false;
    if (link === "feedback" && !obj.has_feedback) return false;
    return true;
  });
  $("#objectList").replaceChildren(...objects.map((obj) => {
    const linked = Boolean((obj.topic_link || {}).l2_id);
    const node = memoryCard(
      obj.obj_id,
      `${obj.type} | imp ${fmtNumber(obj.effective_importance)}`,
      obj.content_preview,
      [
        "l1",
        linked ? { text: "linked", class: "l2" } : { text: "unlinked", class: "unlinked" },
      ],
    );
    node.classList.add("clickable-card", "explorer-object-card");
    if (obj.obj_id === selectedObjectId) node.classList.add("active");
    node.addEventListener("click", () => loadObjectDetail(obj.obj_id));
    return node;
  }));
}

["objectTypeFilter", "objectLinkFilter", "importanceFilter"].forEach((id) => {
  document.addEventListener("input", (event) => {
    if (event.target && event.target.id === id) renderObjects();
  });
});

async function loadObjectDetail(objId) {
  const data = await api(apiWithDataset(`/api/objects/${objId}`));
  selectedObjectId = objId;
  selectedFeedbackObject = data;
  $("#objectDetail").replaceChildren(renderObjectDetail(data));
  $("#feedbackTarget").textContent = objId;
  $("#feedbackImportance").value = data.details.importance || 0.5;
  if (currentObjects.length) renderObjects();
}

function renderObjectDetail(data) {
  const d = data.details || {};
  return el("div", { class: "detail-stack" }, [
    el("h2", { text: d.obj_id || "Object detail" }),
    el("div", { class: "tag-row" }, [
      tag(d.type || "unknown", "l1"),
      tag(d.meeting_id || "meeting", ""),
      tag(`importance ${fmtNumber(d.importance)}`, "feedback"),
    ]),
    el("p", { text: d.content || "" }),
    el("h3", { text: "Evidence" }),
    el("p", { class: "evidence", text: d.evidence || "" }),
    renderTopicLinkBlock(data.topic_link || {}),
    renderFeedbackHistoryBlock(data.feedback_history || []),
    renderCorrectionHistoryBlock(data.correction_history || {}),
  ]);
}

let allTopicData = null;
let currentTopicId = null;

async function loadTopics() {
  allTopicData = await api(apiWithDataset("/api/topics/l3"));
  renderTopicTree();
  const firstChild = (allTopicData.l3_nodes || [])
    .flatMap((family) => family.child_l2_nodes || [])[0];
  const firstUnpromoted = (allTopicData.unpromoted_l2_nodes || [])[0];
  const defaultTopic = firstChild || firstUnpromoted;
  if (!currentTopicId && defaultTopic?.l2_id) {
    await loadTopicDetail(defaultTopic.l2_id);
  }
}

function topicMatchesFilter(node, filterText) {
  if (!filterText) return true;
  const haystack = [
    node.l2_id, node.l3_id, node.label, node.current_state, node.content_preview,
    ...(node.assignment_criteria || []),
  ].join(" ").toLowerCase();
  return haystack.includes(filterText.toLowerCase());
}

function renderTopicTree() {
  const data = allTopicData || { l3_nodes: [], unpromoted_l2_nodes: [] };
  const filterText = ($("#topicSearch") && $("#topicSearch").value) || "";
  const families = [];
  for (const l3 of data.l3_nodes || []) {
    const children = (l3.child_l2_nodes || []).filter((child) => topicMatchesFilter(child, filterText));
    if (filterText && !children.length && !topicMatchesFilter(l3, filterText)) continue;
    families.push(renderL3Family(l3, children));
  }
  const unpromoted = (data.unpromoted_l2_nodes || []).filter((node) => topicMatchesFilter(node, filterText));
  if (unpromoted.length) {
    families.push(el("div", { class: "topic-family unpromoted-family" }, [
      el("div", { class: "topic-family-header" }, [
        tag("L2", "l2"),
        el("div", {}, [
          el("strong", { text: "Unpromoted L2 Topics" }),
          el("div", { class: "label", text: `${unpromoted.length} active L2 topics` }),
        ]),
      ]),
      el("div", { class: "topic-children" }, unpromoted.map(renderL2TopicNode)),
    ]));
  }
  $("#topicTree").replaceChildren(...families);
}

function renderL3Family(l3, children) {
  return el("div", { class: "topic-family" }, [
    el("div", { class: "topic-family-header" }, [
      tag("L3", "l3"),
      el("div", {}, [
        el("strong", { text: l3.label || l3.l3_id }),
        el("div", { class: "label", text: `${l3.l3_id} | ${children.length} child L2 | ${l3.event_count || 0} L1` }),
      ]),
    ]),
    el("div", { class: "topic-children" }, children.map(renderL2TopicNode)),
  ]);
}

function renderL2TopicNode(node) {
  const sizeClass = node.size_bucket ? `size-${node.size_bucket}` : "";
  const topic = el("button", {
    class: `topic-node ${sizeClass}${node.l2_id === currentTopicId ? " active" : ""}`,
    "data-l2-id": node.l2_id || "",
    title: "Open L2 topic detail",
    onclick: () => loadTopicDetail(node.l2_id),
  }, [
    el("span", { class: "node-icon", text: "L2" }),
    el("span", { class: "node-main" }, [
      el("strong", { text: node.label || node.l2_id }),
      el("span", { class: "node-id", text: node.l2_id || "" }),
      el("span", { class: "node-preview", text: preview(node.content_preview || node.current_state || "", 150) }),
    ]),
    el("span", { class: "node-count", text: String(node.event_count || 0) }),
  ]);
  return topic;
}

async function loadTopicDetail(l2Id) {
  currentTopicId = l2Id;
  document.querySelectorAll(".topic-node").forEach((node) => {
    node.classList.toggle("active", node.getAttribute("data-l2-id") === l2Id);
  });
  const data = await api(apiWithDataset(`/api/topics/l2/${encodeURIComponent(l2Id)}`));
  const stats = [
    card("event_count", String(data.event_count || 0)),
    card("size_bucket", data.size_bucket || "unknown"),
    card("parent_l3", data.parent_l3_label || "none"),
    card("linked_l1", String((data.linked_l1_objects || []).length)),
  ];
  $("#topicDetail").replaceChildren(
    el("div", { class: "topic-detail-header" }, [
      el("div", {}, [
        el("h2", { text: data.label || data.l2_id }),
        el("div", { class: "label", text: data.l2_id || "" }),
      ]),
      el("div", { class: "tag-row" }, [
        tag("L2 topic", "l2"),
        data.parent_l3_id ? tag("child L2", "l3") : tag("unpromoted", ""),
        tag(data.size_bucket || "unknown", data.size_bucket === "oversized" ? "warn" : "feedback"),
      ]),
    ]),
    el("div", { class: "cards mini-cards" }, stats),
    renderKeyValueBlock("Current State", data.current_state || data.split_reason || "No state summary."),
    renderCriteria(data.assignment_criteria || []),
    renderTimeline(data.timeline_digest || []),
    renderLinkedObjects(data.linked_l1_objects || []),
  );
}

function renderKeyValueBlock(title, text) {
  return el("div", { class: "subpanel" }, [
    el("h3", { text: title }),
    el("p", { text: text || "" }),
  ]);
}

function renderCriteria(criteria) {
  if (!criteria.length) return el("div");
  return el("div", { class: "subpanel" }, [
    el("h3", { text: "Assignment Criteria" }),
    el("div", { class: "tag-row" }, criteria.map((item) => tag(item, "l2"))),
  ]);
}

function renderTimeline(timeline) {
  const rows = timeline.slice(0, 80).map((event) => el("div", { class: "timeline-event" }, [
    el("div", { class: "timeline-dot" }),
    el("div", {}, [
      el("strong", { text: `${event.meeting_id || ""} | ${event.obj_id || ""}` }),
      el("p", { text: preview(event.summary || event.content || "", 260) }),
    ]),
  ]));
  return el("div", { class: "subpanel" }, [
    el("h3", { text: "Topic Timeline" }),
    el("div", { class: "timeline" }, rows),
  ]);
}

function renderLinkedObjects(objects) {
  const list = objects.map(renderTopicL1Object);
  return el("div", { class: "subpanel" }, [
    el("div", { class: "panel-header" }, [
      el("h3", { text: `Linked L1 Evidence (${objects.length})` }),
      el("span", { class: "label", text: "Click Feedback to adjust importance sidecar." }),
    ]),
    el("div", { class: "l1-list" }, list),
    el("div", { id: "topicInlineFeedback", class: "inline-feedback" }),
  ]);
}

function renderTopicL1Object(obj) {
  const node = el("div", { class: `l1-object-card ${obj.has_feedback ? "has-feedback" : ""}` }, [
    el("div", { class: "object-card-header" }, [
      el("div", {}, [
        el("strong", { text: obj.obj_id || "" }),
        el("div", { class: "label", text: `${obj.meeting_id || ""} | ${obj.type || ""}` }),
      ]),
      el("div", { class: "tag-row" }, [
        tag(`canon ${fmtNumber(obj.canonical_importance)}`, "l1"),
        tag(`eff ${fmtNumber(obj.effective_importance)}`, obj.importance_delta ? "feedback" : ""),
      ]),
    ]),
    el("p", { text: preview(obj.content || obj.content_preview, 280) }),
    el("p", { class: "evidence", text: preview(obj.evidence || obj.evidence_preview, 220) }),
    el("div", { class: "button-row" }, [
      el("button", { class: "secondary", onclick: () => showTopicImportanceEditor(obj), text: "Feedback" }),
      el("button", { class: "secondary", onclick: () => loadObjectDetail(obj.obj_id), text: "Open Detail" }),
    ]),
  ]);
  return node;
}

function showTopicImportanceEditor(obj) {
  const target = $("#topicInlineFeedback");
  target.replaceChildren(importanceEditor(obj, async () => {
    if (currentTopicId) await loadTopicDetail(currentTopicId);
    await loadFeedback();
  }));
  target.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function importanceEditor(obj, afterSave) {
  const canonical = Number(obj.canonical_importance ?? obj.importance ?? 0);
  const current = Number(obj.effective_importance ?? canonical);
  const value = el("span", { class: "importance-value", text: fmtNumber(current) });
  const slider = el("input", { type: "range", min: "0", max: "1", step: "0.01", value: String(current) });
  const reason = el("select", {}, [
    "important_design_decision",
    "important_method_change",
    "important_open_issue",
    "important_evaluation_plan",
    "important_evidence_anchor",
    "minor_repetition",
    "administrative_detail",
    "outdated_or_abandoned",
    "duplicate_or_redundant",
    "wrongly_high",
    "wrongly_low",
    "other",
  ].map((code) => el("option", { text: code, value: code })));
  const note = el("textarea", { placeholder: "note" });
  slider.addEventListener("input", () => {
    value.textContent = fmtNumber(slider.value);
  });
  const save = el("button", { text: "Save importance feedback" });
  save.addEventListener("click", async () => {
    await saveImportanceFeedback(obj, Number(slider.value), reason.value, note.value);
    if (afterSave) await afterSave();
  });
  return el("div", { class: "inline-editor" }, [
    el("h3", { text: `Importance feedback for ${obj.obj_id}` }),
    el("div", { class: "label", text: `Canonical ${fmtNumber(canonical)} | Effective ${fmtNumber(current)}` }),
    el("div", { class: "slider-row" }, [slider, value]),
    reason,
    note,
    save,
  ]);
}

async function saveImportanceFeedback(obj, userImportance, reasonCode, note) {
  if (selectedDataset !== "grace") return;
  await api("/api/feedback/importance", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      obj_id: obj.obj_id,
      meeting_id: obj.meeting_id,
      object_type: obj.type,
      canonical_importance: Number(obj.canonical_importance ?? obj.importance ?? 0),
      user_importance: userImportance,
      reason_code: reasonCode,
      note,
      ...(obj.topic_link || {}),
    }),
  });
}

let selectedFeedbackObject = null;

async function loadFeedback() {
  if (selectedDataset !== "grace") {
    $("#feedbackObjects").replaceChildren(el("p", {
      class: "muted",
      text: "ICSI mode is read-only for this screenshot workflow. The sidecar workflow is implemented in Grace mode; raw L1 remains unchanged.",
    }));
    $("#feedbackSummary").textContent = JSON.stringify({ dataset: selectedDataset, read_only: true }, null, 2);
    return;
  }
  const objects = await api(apiWithDataset("/api/objects")).catch(() => []);
  $("#feedbackObjects").replaceChildren(...objects.map((obj) => {
    const tags = [];
    if (obj.has_feedback) tags.push("feedback");
    if (obj.has_corrections) tags.push({ text: "corrected", class: "feedback" });
    const node = memoryCard(obj.obj_id, `${obj.type} | canonical ${fmtNumber(obj.canonical_importance)}`, obj.content_preview, tags);
    node.classList.add("clickable-card");
    node.addEventListener("click", () => loadObjectDetail(obj.obj_id));
    return node;
  }));
  const [summary, corrections] = await Promise.all([
    api("/api/feedback/summary"),
    api("/api/feedback/corrections/summary"),
  ]);
  $("#feedbackSummary").textContent = JSON.stringify({ importance: summary, corrections }, null, 2);
}

$("#saveFeedback").addEventListener("click", async () => {
  if (!selectedFeedbackObject) return;
  const d = selectedFeedbackObject.details;
  await saveImportanceFeedback(
    { ...d, topic_link: selectedFeedbackObject.topic_link },
    Number($("#feedbackImportance").value),
    $("#feedbackReason").value,
    $("#feedbackNote").value,
  );
  await loadFeedback();
});

async function saveSummaryCorrection() {
  if (!selectedFeedbackObject || selectedDataset !== "grace") return;
  const d = selectedFeedbackObject.details || {};
  await api("/api/feedback/summary-corrections", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      obj_id: d.obj_id,
      meeting_id: d.meeting_id,
      canonical_content: d.content || "",
      corrected_content: $("#summaryCorrectionText").value,
      reason_code: $("#summaryCorrectionReason").value,
      note: "Saved from Memory Observatory; raw L1 remains unchanged.",
    }),
  });
  await loadObjectDetail(d.obj_id);
  await loadFeedback();
}

async function saveValidityFlag() {
  if (!selectedFeedbackObject || selectedDataset !== "grace") return;
  const d = selectedFeedbackObject.details || {};
  await api("/api/feedback/validity-flags", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      obj_id: d.obj_id,
      meeting_id: d.meeting_id,
      flag_type: $("#validityFlagType").value,
      reason_code: $("#validityFlagType").value,
      note: $("#validityFlagNote").value,
    }),
  });
  await loadObjectDetail(d.obj_id);
  await loadFeedback();
}

async function saveTopicLinkReview() {
  if (!selectedFeedbackObject || selectedDataset !== "grace") return;
  const d = selectedFeedbackObject.details || {};
  const link = selectedFeedbackObject.topic_link || {};
  await api("/api/feedback/topic-link-reviews", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      obj_id: d.obj_id,
      meeting_id: d.meeting_id,
      action: $("#topicLinkAction").value,
      l2_id: link.l2_id || $("#topicLinkTarget").value,
      l2_label: link.l2_label || $("#topicLinkTarget").value,
      child_l2_id: link.child_l2_id || "",
      parent_l3_id: link.parent_l3_id || "",
      reason_code: "human_topic_review",
      note: $("#topicLinkNote").value,
    }),
  });
  await loadObjectDetail(d.obj_id);
  await loadFeedback();
}

$("#saveSummaryCorrection").addEventListener("click", saveSummaryCorrection);
$("#saveValidityFlag").addEventListener("click", saveValidityFlag);
$("#saveTopicLinkReview").addEventListener("click", saveTopicLinkReview);

async function loadRuns() {
  const runs = await api("/api/runs");
  $("#runSelect").replaceChildren(...runs.map((r) => el("option", { value: r.run_id, text: r.run_id })));
  if (runs[0]) await loadRun(runs[0].run_id);
}

async function loadRun(runId) {
  const data = await api(`/api/runs/${runId}`);
  const summary = data.summary || {};
  currentRunQueries = data.queries || [];
  selectedQueryId = currentRunQueries[0]?.query_id || "";
  $("#runSummary").replaceChildren(
    card("queries", String(summary.query_count || 0)),
    metricSummaryCard("avg context tokens", summary.avg_context_tokens || {}, "number"),
    metricSummaryCard("avg total time", summary.avg_total_ms || {}, "ms"),
  );
  renderQueryList();
  if (currentRunQueries[0]) {
    showQueryDetail(currentRunQueries[0]);
  } else {
    $("#queryDetail").replaceChildren(el("p", { class: "muted", text: "This run has no query details." }));
  }
}

function renderQueryList() {
  $("#queryCount").textContent = `${currentRunQueries.length} total`;
  $("#queryTable").replaceChildren(...currentRunQueries.map((q) => {
    const tags = [
      q.category ? { text: q.category, class: "" } : null,
      q.expected_route ? { text: q.expected_route, class: "l2" } : null,
    ].filter(Boolean);
    const node = memoryCard(q.query_id, q.query, q.expected_answer || "open details", tags);
    node.classList.add("clickable-card", "lab-query-card");
    if (q.query_id === selectedQueryId) node.classList.add("active");
    node.addEventListener("click", () => {
      selectedQueryId = q.query_id || "";
      renderQueryList();
      showQueryDetail(q);
    });
    return node;
  }));
}

function showQueryDetail(q) {
  const strategies = ["full_context", "rag_baseline", "layered_memory"];
  $("#queryDetail").replaceChildren(
    renderQueryHeader(q),
    el("div", { class: "strategy-compare" }, strategies.map((s) => renderStrategyDetail(s, (q.strategies || {})[s] || {}))),
  );
}

function renderQueryHeader(q) {
  const expectedObjCount = (q.expected_obj_ids || []).length;
  const expectedL2Count = (q.expected_l2_ids || []).length;
  const expectedL3Count = (q.expected_l3_ids || []).length;
  return el("div", { class: "query-detail-header" }, [
    el("div", { class: "query-title-row" }, [
      el("div", {}, [
        el("div", { class: "label", text: q.query_id || "Query" }),
        el("h2", { text: q.query || "" }),
      ]),
      el("div", { class: "tag-row" }, [
        q.category ? tag(q.category, "") : null,
        q.expected_route ? tag(q.expected_route, "l2") : null,
        q.expected_winner ? tag(q.expected_winner, "feedback") : null,
      ]),
    ]),
    el("div", { class: "query-context-grid" }, [
      el("div", { class: "subpanel" }, [
        el("h3", { text: "Expected Answer" }),
        el("p", { class: "answer-text", text: q.expected_answer || "No expected answer attached to this query." }),
      ]),
      el("div", { class: "subpanel" }, [
        el("h3", { text: "Gold Targets" }),
        keyValueRows([
          { label: "L1 objects", value: expectedObjCount },
          { label: "L2 topics", value: expectedL2Count },
          { label: "L3 topics", value: expectedL3Count },
          { label: "Meetings", value: (q.gold_meeting_ids || []).join(", ") },
        ]),
      ]),
    ]),
  ]);
}

function metricValue(metrics, key, kind = "number") {
  const value = metrics ? metrics[key] : undefined;
  if (value === undefined || value === null || value === "") return "0";
  return formatMetricValue(value, kind);
}

function renderStrategyDetail(strategy, item) {
  const metrics = item.metrics || {};
  const scores = item.scores || {};
  const answer = item.answer || "";
  return el("div", { class: `panel strategy-detail ${strategy}` }, [
    el("div", { class: "panel-header" }, [
      el("h2", { text: STRATEGY_LABELS[strategy] || strategy }),
      el("div", { class: "tag-row" }, [
        item.truncated || metrics.truncated ? tag("budget limited", "warn") : tag("not limited", "feedback"),
        strategy === "layered_memory" ? tag("L1 -> L2/L3", "l2") : null,
        strategy === "rag_baseline" ? tag("chunks", "rag") : null,
      ]),
    ]),
    el("div", { class: "strategy-metrics" }, [
      keyValueRows([
        { label: "Context", value: metricValue(metrics, "estimated_context_tokens") },
        { label: "Total tok.", value: metricValue(metrics, "actual_total_tokens") },
        { label: "Total time", value: metricValue(metrics, "total_ms", "ms") },
        { label: "Generation", value: metricValue(metrics, "generation_ms", "ms") },
      ]),
      scores.expected_obj_recall_at_context !== undefined ? keyValueRows([
        { label: "L1 recall", value: fmtNumber(scores.expected_obj_recall_at_context) },
        { label: "L2 hit", value: scores.expected_l2_hit ? "yes" : "no" },
        { label: "L3 hit", value: scores.expected_l3_hit ? "yes" : "no" },
        { label: "Omitted events", value: metricValue(metrics, "omitted_event_count") },
      ]) : null,
    ]),
    el("div", { class: "answer-box" }, [
      el("h3", { text: "Answer" }),
      el("p", { class: "answer-text", text: answer ? preview(answer, 1800) : "No answer generated in this run." }),
    ]),
    renderStrategyEvidence(strategy, item),
  ]);
}

function renderStrategyEvidence(strategy, item) {
  if (strategy === "rag_baseline") {
    const chunks = item.retrieved_chunks || [];
    return el("div", { class: "subpanel" }, [
      el("h3", { text: `Retrieved Chunks (${chunks.length})` }),
      ...chunks.slice(0, 4).map((chunk) => el("div", { class: "evidence-card rag-evidence" }, [
        el("strong", { text: chunk.chunk_id || "chunk" }),
        el("div", { class: "label", text: `${chunk.meeting_id || ""} | lines ${chunk.start_line || "?"}-${chunk.end_line || "?"} | score ${fmtNumber(chunk.score)}` }),
        el("p", { text: preview(chunk.text, 260) }),
      ])),
      chunks.length > 4 ? el("p", { class: "muted", text: `${chunks.length - 4} more chunks omitted from the demo panel.` }) : null,
    ]);
  }
  if (strategy === "layered_memory") {
    const l1 = item.l1_evidence_seeds || [];
    const l2 = item.l2_evolution_context || [];
    return el("div", { class: "subpanel" }, [
      el("h3", { text: `L1 Evidence Seeds (${l1.length})` }),
      ...l1.slice(0, 5).map((obj) => el("div", { class: "evidence-card l1-evidence" }, [
        el("strong", { text: obj.obj_id || "" }),
        el("div", { class: "label", text: `${obj.meeting_id || ""} | ${obj.type || ""} | score ${fmtNumber(obj.score)}` }),
        el("p", { text: preview(obj.content, 240) }),
      ])),
      l1.length > 5 ? el("p", { class: "muted", text: `${l1.length - 5} more L1 seeds omitted from the demo panel.` }) : null,
      el("h3", { text: `L2 / Child-L2 Context (${l2.length})` }),
      ...l2.slice(0, 3).map((topic) => el("div", { class: "evidence-card l2-evidence" }, [
        el("strong", { text: topic.label || topic.l2_id || "" }),
        el("div", { class: "label", text: `${topic.l2_id || ""} | omitted ${topic.omitted_event_count || 0}` }),
        el("p", { text: preview(topic.current_state || timelineText(topic.timeline_digest), 260) }),
      ])),
    ]);
  }
  return el("div", { class: "subpanel" }, [
    el("h3", { text: "Included Context" }),
    keyValueRows([
      { label: "Meetings", value: item.included_meeting_count },
      { label: "Files", value: item.included_file_count },
      { label: "Source", value: item.full_context_source || item.source },
    ]),
  ]);
}

function timelineText(timeline) {
  if (!Array.isArray(timeline)) return "";
  return timeline.map((event) => `${event.meeting_id || ""} ${event.obj_id || ""}: ${event.summary || event.content || ""}`).join(" ");
}

$("#topicSearch").addEventListener("input", renderTopicTree);
$("#runSelect").addEventListener("change", (e) => loadRun(e.target.value));
$("#refreshRuns").addEventListener("click", loadRuns);
$("#runExperiment").addEventListener("click", async () => {
  const result = await api("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      strategies: ["full_context", "rag_baseline", "layered_memory"],
      retrieval_mode: "hybrid",
      no_llm: true,
      generate_answers: false,
      planner_model: "",
      max_context_chars: 0,
    }),
  });
  await loadRuns();
  $("#runSelect").value = result.run_id;
});
$("#runTrace").addEventListener("click", runTrace);
document.querySelectorAll("[data-demo-query]").forEach((button) => {
  button.addEventListener("click", () => {
    $("#traceQuery").value = button.dataset.demoQuery || "";
    runTrace();
  });
});
$("#traceNoLlm").addEventListener("change", syncTracePlannerControl);
syncTracePlannerControl();

async function boot() {
  const hashTab = (window.location.hash || "").replace("#", "");
  activateTab(hashTab || "demo", false);
  await loadDatasets();
  await loadOverview();
  await loadDemoStory();
  await loadExplorer();
  await loadTopics();
  await loadFeedback();
  await loadRuns();
  if (hashTab === "trace") {
    $("#traceQuery").value = DEMO_TRACE_QUERY;
    $("#traceDebug").checked = false;
    $("#traceMode").value = "lexical";
    if ($("#traceBudgetProfile")) $("#traceBudgetProfile").value = "observatory_paper_trace";
    await runTrace();
  }
  if (hashTab === "topics") {
    $("#topicSearch").value = selectedDataset === "icsi" ? "audio" : "transcript";
    renderTopicTree();
    if (selectedDataset === "grace") {
      await loadTopicDetail("L2-idea-unit-generation-methods").catch(() => {});
    }
  }
}

boot();
