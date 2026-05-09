const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
};
const api = async (url, opts) => {
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  const type = res.headers.get("content-type") || "";
  return type.includes("json") ? res.json() : res.text();
};
const card = (title, body, tags = []) => el("div", { class: "card" }, [
  el("div", { class: "label", text: title }),
  el("div", { class: "value", text: body }),
  el("div", {}, tags.map((t) => el("span", { class: `tag ${t.class || ""}`, text: t.text }))),
]);
const preview = (text, n = 220) => (text || "").length > n ? `${text.slice(0, n)}...` : (text || "");

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
      memoryCard(item.obj_id, `${item.meeting_id} · ${item.type} · score ${item.score}`, item.content, ["l1"])),
    listSection("L2 / Child-L2 Evolution Context", data.l2_evolution_context, (item) =>
      memoryCard(item.l2_id, `${item.label || ""} · omitted ${item.omitted_event_count || 0}`, item.current_state || item.timeline_digest, ["l2"])),
    section("Formatted Prompt Context", data.formatted_prompt_context, true),
  );
}

function section(title, text, pre = false) {
  return el("div", { class: "panel" }, [el("h2", { text: title }), pre ? el("pre", { text }) : el("pre", { text })]);
}
function listSection(title, items, render) {
  return el("div", { class: "panel" }, [el("h2", { text: title }), ...((items || []).map(render))]);
}
function memoryCard(title, meta, body, tags = []) {
  return el("div", { class: "card" }, [
    el("strong", { text: title || "" }),
    el("div", { class: "label", text: meta || "" }),
    el("p", { text: preview(typeof body === "string" ? body : JSON.stringify(body)) }),
    el("div", {}, tags.map((tag) => el("span", { class: `tag ${tag}`, text: tag }))),
  ]);
}

async function loadExplorer() {
  const meetings = await api("/api/meetings");
  $("#meetingList").replaceChildren(...meetings.map((m) => {
    const node = memoryCard(m.meeting_id, `${m.meeting_date} · ${m.object_count} objects`, `${m.high_importance_count} high importance`, []);
    node.addEventListener("click", () => loadObjects(m.meeting_id));
    return node;
  }));
  if (meetings[0]) await loadObjects(meetings[0].meeting_id);
}
let currentObjects = [];
async function loadObjects(meetingId) {
  currentObjects = await api(`/api/meetings/${meetingId}/objects`);
  const types = [...new Set(currentObjects.map((obj) => obj.type).filter(Boolean))].sort();
  $("#objectTypeFilter").replaceChildren(el("option", { value: "", text: "all types" }), ...types.map((t) => el("option", { value: t, text: t })));
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
    const node = memoryCard(obj.obj_id, `${obj.type} · imp ${obj.effective_importance}`, obj.content_preview, ["l1"]);
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
  $("#objectDetail").replaceChildren(el("pre", { text: JSON.stringify(data, null, 2) }));
  selectedFeedbackObject = data;
  $("#feedbackTarget").textContent = objId;
  $("#feedbackImportance").value = data.details.importance || 0.5;
}

async function loadTopics() {
  const data = await api("/api/topics/l3");
  const nodes = [];
  for (const l3 of data.l3_nodes || []) {
    nodes.push(memoryCard(l3.l3_id, l3.label, `${(l3.child_l2_nodes || []).length} child L2`, ["l3"]));
    for (const child of l3.child_l2_nodes || []) {
      const node = memoryCard(`  ${child.l2_id}`, child.label, `${(child.linked_obj_ids || []).length} L1`, ["l2"]);
      node.addEventListener("click", () => loadTopicDetail(child.l2_id));
      nodes.push(node);
    }
  }
  for (const l2 of data.unpromoted_l2_nodes || []) {
    const node = memoryCard(l2.l2_id, l2.label, `${l2.event_count} L1`, ["l2"]);
    node.addEventListener("click", () => loadTopicDetail(l2.l2_id));
    nodes.push(node);
  }
  $("#topicTree").replaceChildren(...nodes);
}
async function loadTopicDetail(l2Id) {
  const data = await api(`/api/topics/l2/${encodeURIComponent(l2Id)}`);
  $("#topicDetail").replaceChildren(el("pre", { text: JSON.stringify(data, null, 2) }));
}

let selectedFeedbackObject = null;
async function loadFeedback() {
  const objects = await api("/api/objects").catch(() => []);
  $("#feedbackObjects").replaceChildren(...objects.map((obj) => {
    const node = memoryCard(obj.obj_id, `${obj.type} · canonical ${obj.canonical_importance}`, obj.content_preview, obj.has_feedback ? ["feedback"] : []);
    node.addEventListener("click", () => loadObjectDetail(obj.obj_id));
    return node;
  }));
  const summary = await api("/api/feedback/summary");
  $("#feedbackSummary").textContent = JSON.stringify(summary, null, 2);
}
$("#saveFeedback").addEventListener("click", async () => {
  if (!selectedFeedbackObject) return;
  const d = selectedFeedbackObject.details;
  await api("/api/feedback/importance", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      obj_id: d.obj_id,
      meeting_id: d.meeting_id,
      object_type: d.type,
      canonical_importance: d.importance,
      user_importance: Number($("#feedbackImportance").value),
      reason_code: $("#feedbackReason").value,
      note: $("#feedbackNote").value,
      ...selectedFeedbackObject.topic_link,
    }),
  });
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
