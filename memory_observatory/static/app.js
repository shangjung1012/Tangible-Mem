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
const DEMO_TRACE_QUERY = "為什麼不要把完整 transcription 一次丟進模型，而要切成 segment 和 idea units？";

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
        el("h2", { text: "Layered Memory recovers much more evidence than RAG" }),
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
  if (value.includes("fixed") || value.includes("dynamic")) return "How much transcript text should be grouped before extraction.";
  if (value.includes("generation")) return "How transcript windows become concrete idea-unit candidates.";
  if (value.includes("classification")) return "How candidate units are typed before entering memory.";
  if (value.includes("granularity")) return "How fine-grained an idea unit should be.";
  if (value.includes("definition")) return "What separates a segment from an idea unit.";
  if (value.includes("window") || value.includes("boundary")) return "How coherent discussion boundaries are selected.";
  if (value.includes("evidence")) return "How topic memory remains grounded in transcript evidence.";
  return "Durable child topic state built from linked L1 evidence.";
}

function findDemoTranscriptFamily(topics) {
  const families = (topics || {}).l3_nodes || [];
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

function renderDemoQueryFlow(family, seeds, contexts, siblingLabels) {
  const dates = [...new Set(seeds.map((seed) => seed.meeting_id).filter(Boolean))];
  const primaryContext = contexts[0] || {};
  return el("section", { class: "demo-section demo-query-map-section" }, [
    el("div", { class: "demo-section-copy" }, [
      el("div", { class: "demo-eyebrow", text: "Teaser query retrieves layered memory" }),
      el("h2", { text: "One question becomes a traceable retrieval path" }),
      el("p", { text: "The query does not directly summarize all transcripts. It starts from source-grounded L1 evidence, then brings in the relevant L2 evolution and parent L3 navigation." }),
    ]),
    el("div", { class: "demo-query-map" }, [
      el("div", { class: "demo-flow-card query" }, [
        el("span", { text: "User query" }),
        el("strong", { text: "Why split transcripts into segments / idea units?" }),
      ]),
      el("div", { class: "demo-flow-arrow", text: "->" }),
      el("div", { class: "demo-flow-card l1" }, [
        el("span", { text: "Retrieved L1 evidence seeds" }),
        el("strong", { text: dates.join(" / ") || "0422 / 0429 / 0506" }),
        el("p", { text: "Source evidence from meetings, not a generated summary." }),
      ]),
      el("div", { class: "demo-flow-arrow", text: "->" }),
      el("div", { class: "demo-flow-card l2" }, [
        el("span", { text: "Matched L2 topic evolution" }),
        el("strong", { text: primaryContext.label || "idea-unit generation methods" }),
        el("p", { text: "Shows how the design rationale evolved across meetings." }),
      ]),
      el("div", { class: "demo-flow-arrow", text: "->" }),
      el("div", { class: "demo-flow-card l3" }, [
        el("span", { text: "Parent L3 family" }),
        el("strong", { text: family.label || "transcript segmentation and idea-unit coverage" }),
        el("p", { text: `${Math.max(siblingLabels.length, 0)} related topic node(s) visible as navigation.` }),
      ]),
    ]),
  ]);
}

function selectDemoEvidenceSeeds(seeds) {
  const preferredMeetings = ["0422", "0429", "0506"];
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

function renderDemoSingleTraceResult(family, seeds, contexts, siblingLabels) {
  const selectedSeeds = selectDemoEvidenceSeeds(seeds);
  const context = contexts[0] || {};
  const contextText = context.evolution_summary || context.current_state || timelineText(context.timeline_digest || []);
  const relatedTopics = siblingLabels.slice(0, 3).map((child) => child.label || child.l2_id).filter(Boolean);
  return el("section", { class: "demo-section demo-single-trace-section" }, [
    el("div", { class: "demo-single-head" }, [
      el("div", { class: "demo-eyebrow", text: "Retrieval trace result" }),
      el("h2", { text: "What this one query retrieves" }),
      el("p", { text: "The query first finds source-grounded L1 evidence, then uses those seeds to pull the relevant L2 evolution and L3 topic family." }),
    ]),
    el("div", { class: "demo-single-grid" }, [
      el("div", { class: "demo-single-card query" }, [
        el("span", { text: "Teaser query" }),
        el("strong", { text: "Why did we split transcripts into segments and idea units?" }),
        el("p", { text: "A rationale question about design evolution." }),
      ]),
      el("div", { class: "demo-single-card l1" }, [
        el("span", { text: "L1 evidence seeds" }),
        el("strong", { text: selectedSeeds.map((seed) => seed.meeting_id).join(" / ") || "0422 / 0429 / 0506" }),
        el("div", { class: "demo-seed-stack" }, selectedSeeds.map((seed) =>
          el("div", { class: "demo-seed-row" }, [
            tag(seed.meeting_id || "meeting", "l1"),
            el("b", { text: seed.obj_id || "" }),
            el("p", { text: preview(seed.content || seed.evidence, 112) }),
          ])
        )),
      ]),
      el("div", { class: "demo-single-card l2" }, [
        el("span", { text: "L2 topic evolution" }),
        el("strong", { text: context.label || "idea-unit generation methods" }),
        el("p", { text: preview(contextText, 260) }),
        el("div", { class: "tag-row" }, [
          tag(`${context.selected_event_count || 0} selected event`, "l2"),
          tag(`${context.omitted_event_count || 0} omitted`, "muted"),
        ]),
      ]),
      el("div", { class: "demo-single-card l3" }, [
        el("span", { text: "Parent L3 topic family" }),
        el("strong", { text: family.label || "transcript segmentation and idea-unit coverage" }),
        el("p", { text: "Navigation context: shows this rationale belongs to a broader transcript segmentation / idea-unit coverage family." }),
        el("div", { class: "tag-row" }, relatedTopics.map((topic) => tag(topic, "l2"))),
      ]),
    ]),
  ]);
}

function renderDemoStory(topics, trace) {
  const family = findDemoTranscriptFamily(topics);
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
    renderDemoSingleTraceResult(family, seeds, contexts, siblingLabels),
    renderDemoQueryFlow(family, seeds, contexts, siblingLabels),
    el("section", { class: "demo-section demo-topic-section" }, [
      el("div", { class: "demo-section-copy" }, [
        el("div", { class: "demo-eyebrow", text: "1. Topic Observatory" }),
        el("h2", { text: "The topic family exists before the query" }),
        el("p", { text: "This is persistent topic memory: L2 topic states and L3 family links exist before the user asks anything." }),
        el("div", { class: "demo-family-card" }, [
          el("div", { class: "tag-row" }, [
            tag("L3 topic family", "l3"),
            tag(`${children.length} shown topic nodes`, "l2"),
            tag(`${family.event_count || 0} linked L1`, "l1"),
          ]),
          el("strong", { text: family.label || family.l3_id || "transcript segmentation and idea-unit coverage" }),
          el("span", { class: "label", text: family.l3_id || "" }),
          el("p", { text: "L3 is navigation context; factual claims still come from linked L1 evidence." }),
        ]),
      ]),
      el("div", { class: "demo-child-grid" }, children.map(renderDemoChildTopic)),
    ]),
    el("section", { class: "demo-section demo-trace-section" }, [
      el("div", { class: "demo-section-copy" }, [
        el("div", { class: "demo-eyebrow", text: "2. Retrieval Trace" }),
        el("h2", { text: "The query becomes an evidence-first memory trace" }),
        el("p", { text: DEMO_TRACE_QUERY }),
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
        el("div", { class: "demo-eyebrow", text: "3. Baseline contrast" }),
        el("h2", { text: "The difference is what each system injects" }),
        el("p", { text: "Full Context is broad, RAG is local, and Layered Memory is evidence-grounded plus evolution-aware." }),
      ]),
      renderDemoComparison(),
    ]),
  );
}

async function loadDemoStory() {
  const target = $("#demoStory");
  if (!target) return;
  target.className = "demo-story loading";
  target.textContent = "Loading demo trace...";
  try {
    const [topics, trace] = await Promise.all([
      api("/api/topics/l3?dataset=grace"),
      api(`/api/retrieval/trace?query=${encodeURIComponent(DEMO_TRACE_QUERY)}&retrieval_mode=hybrid&no_llm=true&include_debug=false&budget_profile=observatory_trace`),
    ]);
    renderDemoStory(topics, trace);
  } catch (error) {
    target.className = "demo-story error";
    target.textContent = `Could not load demo story: ${error.message}`;
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
  const hashTab = (window.location.hash || "").replace("#", "");
  if (["demo", "trace", "topics"].includes(hashTab)) {
    selectedDataset = "grace";
  }
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
  const fullTopic = await api(`/api/topics/l2/${encodeURIComponent(traceItem.l2_id)}`);
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
  const budgetProfile = "observatory_trace";
  const data = await api(`/api/retrieval/trace?query=${q}&retrieval_mode=${mode}&no_llm=${noLlm}&include_debug=false&planner_model=${plannerModel}&budget_profile=${budgetProfile}`);
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
  $("#objectDetail").replaceChildren(el("p", { class: "muted", text: "Select an L1 object to inspect details." }));
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
  ]);
}

let allTopicData = null;
let currentTopicId = null;

async function loadTopics() {
  allTopicData = await api(apiWithDataset("/api/topics/l3"));
  renderTopicTree();
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
    class: `topic-node ${sizeClass}`,
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
      text: "ICSI mode is read-only for this screenshot workflow. Importance feedback remains available in Grace mode.",
    }));
    $("#feedbackSummary").textContent = JSON.stringify({ dataset: selectedDataset, read_only: true }, null, 2);
    return;
  }
  const objects = await api(apiWithDataset("/api/objects")).catch(() => []);
  $("#feedbackObjects").replaceChildren(...objects.map((obj) => {
    const node = memoryCard(obj.obj_id, `${obj.type} | canonical ${fmtNumber(obj.canonical_importance)}`, obj.content_preview, obj.has_feedback ? ["feedback"] : []);
    node.classList.add("clickable-card");
    node.addEventListener("click", () => loadObjectDetail(obj.obj_id));
    return node;
  }));
  const summary = await api("/api/feedback/summary");
  $("#feedbackSummary").textContent = JSON.stringify(summary, null, 2);
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
  await loadDatasets();
  await loadOverview();
  await loadDemoStory();
  await loadExplorer();
  await loadTopics();
  await loadFeedback();
  await loadRuns();
  if (hashTab) activateTab(hashTab, false);
  if (hashTab === "trace") {
    $("#traceQuery").value = DEMO_TRACE_QUERY;
    $("#traceDebug").checked = false;
    await runTrace();
  }
  if (hashTab === "topics") {
    $("#topicSearch").value = "transcript";
    renderTopicTree();
    await loadTopicDetail("L2-idea-unit-generation-methods").catch(() => {});
  }
}

boot();
