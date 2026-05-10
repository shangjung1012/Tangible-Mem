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

async function runTrace() {
  const q = encodeURIComponent($("#traceQuery").value);
  const mode = $("#traceMode").value;
  const noLlm = $("#traceNoLlm").checked;
  const debug = $("#traceDebug").checked;
  const plannerModel = encodeURIComponent($("#tracePlannerModel").value || "");
  const data = await api(`/api/retrieval/trace?query=${q}&retrieval_mode=${mode}&no_llm=${noLlm}&include_debug=${debug}&planner_model=${plannerModel}`);
  const out = $("#traceOutput");
  out.replaceChildren(
    card("Query / Plan", `${data.metrics.selected_l1_count} L1, ${data.metrics.selected_l2_count} L2, ${data.metrics.selected_child_l2_count} child L2`, [
      { text: data.retrieval_mode },
      { text: data.use_llm_planner ? "LLM planner" : "heuristic" },
      { text: `planner: ${data.planner_model || ""}` },
      { text: `answer: ${data.answer_model || ""}` },
    ]),
    section("Global Topic Map", JSON.stringify(data.global_topic_map, null, 2)),
    listSection("L1 Evidence Seeds", data.l1_evidence_seeds, (item) =>
      memoryCard(item.obj_id, `${item.meeting_id} | ${item.type} | score ${item.score}`, item.content, ["l1"])),
    listSection("L2 / Child-L2 Evolution Context", data.l2_evolution_context, (item) =>
      memoryCard(item.l2_id, `${item.label || ""} | omitted ${item.omitted_event_count || 0}`, item.current_state || item.timeline_digest, ["l2"])),
    section("Formatted Prompt Context", data.formatted_prompt_context),
  );
}

async function loadExplorer() {
  const meetings = await api("/api/meetings");
  $("#meetingList").replaceChildren(...meetings.map((m) => {
    const node = memoryCard(m.meeting_id, `${m.meeting_date} | ${m.object_count} objects`, `${m.high_importance_count} high importance`, []);
    node.addEventListener("click", () => loadObjects(m.meeting_id));
    return node;
  }));
  if (meetings[0]) await loadObjects(meetings[0].meeting_id);
}

let currentObjects = [];

async function loadObjects(meetingId) {
  currentObjects = await api(`/api/meetings/${meetingId}/objects`);
  const types = [...new Set(currentObjects.map((obj) => obj.type).filter(Boolean))].sort();
  $("#objectTypeFilter").replaceChildren(
    el("option", { value: "", text: "all types" }),
    ...types.map((t) => el("option", { value: t, text: t })),
  );
  renderObjects();
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
    const node = memoryCard(obj.obj_id, `${obj.type} | imp ${fmtNumber(obj.effective_importance)}`, obj.content_preview, ["l1"]);
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
  selectedFeedbackObject = data;
  $("#objectDetail").replaceChildren(renderObjectDetail(data));
  $("#feedbackTarget").textContent = objId;
  $("#feedbackImportance").value = data.details.importance || 0.5;
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
    el("h3", { text: "Topic Links" }),
    el("pre", { text: JSON.stringify(data.topic_link || {}, null, 2) }),
    el("h3", { text: "Feedback History" }),
    el("pre", { text: JSON.stringify(data.feedback_history || [], null, 2) }),
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
  $("#runSummary").replaceChildren(
    card("queries", String(summary.query_count || 0)),
    card("avg context tokens", JSON.stringify(summary.avg_context_tokens || {})),
    card("avg total ms", JSON.stringify(summary.avg_total_ms || {})),
  );
  $("#queryTable").replaceChildren(...(data.queries || []).map((q) => {
    const node = memoryCard(q.query_id, q.query, "open details", []);
    node.addEventListener("click", () => showQueryDetail(q));
    return node;
  }));
}

function showQueryDetail(q) {
  const strategies = ["full_context", "rag_baseline", "layered_memory"];
  $("#queryDetail").replaceChildren(...strategies.map((s) => {
    const item = (q.strategies || {})[s] || {};
    return el("div", { class: "panel" }, [
      el("h2", { text: s }),
      el("pre", { text: JSON.stringify({ metrics: item.metrics, scores: item.scores, retrieved_chunks: item.retrieved_chunks, l1: item.l1_evidence_seeds }, null, 2) }),
    ]);
  }));
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
      retrieval_mode: "lexical",
      no_llm: true,
      generate_answers: false,
      planner_model: "gemini-2.5-flash",
      max_context_chars: 4000,
    }),
  });
  await loadRuns();
  $("#runSelect").value = result.run_id;
});
$("#runTrace").addEventListener("click", runTrace);

loadOverview();
loadExplorer();
loadTopics();
loadFeedback();
loadRuns();
