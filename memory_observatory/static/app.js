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

function card(title, body, tags = []) {
  return el("div", { class: "card" }, [
    el("div", { class: "label", text: title }),
    el("div", { class: "value", text: body }),
    el("div", {}, tags.map((t) => tag(t.text || t, t.class || ""))),
  ]);
}

const STRATEGY_LABELS = {
  full_context: "Full context",
  rag_baseline: "RAG",
  layered_memory: "Layered memory",
};

let currentRunQueries = [];
let selectedQueryId = "";

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

document.querySelectorAll(".nav").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav,.tab").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    $(`#${button.dataset.tab}`).classList.add("active");
  });
});

async function loadOverview() {
  const data = await api("/api/overview");
  const fields = [
    "meeting_count", "l1_object_count", "l2_topic_count", "linked_l1_count",
    "unlinked_l1_count", "materialized_l3_count", "child_l2_count",
    "l3_assigned_l1_count", "l3_unassigned_l1_count", "duplicate_assignment_count",
    "invalid_l3_index_count", "retrieval_eval_query_count", "retrieval_eval_run_count",
  ];
  $("#overviewCards").replaceChildren(...fields.map((key) => card(key, String(data[key] ?? 0))));
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
  currentMeetings = await api("/api/meetings");
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
  currentObjects = await api(`/api/meetings/${meetingId}/objects`);
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
  const data = await api(`/api/objects/${objId}`);
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
  allTopicData = await api("/api/topics/l3");
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
  const data = await api(`/api/topics/l2/${encodeURIComponent(l2Id)}`);
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
  const objects = await api("/api/objects").catch(() => []);
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

loadOverview();
loadExplorer();
loadTopics();
loadFeedback();
loadRuns();
