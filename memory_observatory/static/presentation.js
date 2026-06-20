const q = (selector) => document.querySelector(selector);

const make = (tag, attrs = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
};

const api = async (url) => {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
};

const QUERY = "What context about delay-and-sum beamforming and close microphones should carry over to later audio processing discussions?";

function preview(text, n = 210) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  return value.length > n ? `${value.slice(0, n)}...` : value;
}

function topicDescription(label) {
  const value = String(label || "").toLowerCase();
  if (value.includes("audio")) return "How audio capture, channels, filtering, and signal processing are preserved across meetings.";
  if (value.includes("annotation") || value.includes("transcription")) return "How annotation and transcription workflows become inspectable topic memory.";
  if (value.includes("asr") || value.includes("speech recognition")) return "How ASR modeling context carries forward across BMR discussions.";
  if (value.includes("corpus") || value.includes("data")) return "How corpus design and data-management decisions accumulate over time.";
  if (value.includes("project") || value.includes("agenda")) return "How planning context stays visible without replacing L1 evidence.";
  if (value.includes("evidence")) return "How topic memory stays grounded in source transcript evidence.";
  return "Durable topic state built from linked L1 evidence.";
}

function badge(text, cls = "") {
  return make("span", { class: `badge ${cls}`, text });
}

function findPresentationFamily(data) {
  const families = data.l3_nodes || [];
  return families.find((item) => {
    const haystack = `${item.l3_id || ""} ${item.label || ""}`.toLowerCase();
    return haystack.includes("audio acquisition") || haystack.includes("signal processing") || haystack.includes("audio");
  }) || families[0] || {};
}

function renderTopicStory(data) {
  const family = findPresentationFamily(data);
  const children = (family.child_l2_nodes || []).slice().sort((a, b) =>
    Number(b.event_count || 0) - Number(a.event_count || 0)
  );
  const featuredIds = [
    "audio",
    "signal",
    "processing",
    "microphone",
    "speech",
    "asr",
  ];
  const childNodes = children.slice(0, 6).map((child) => {
    const label = child.label || child.l2_id || "";
    const haystack = `${label} ${child.l2_id || ""}`.toLowerCase();
    const featured = featuredIds.some((term) => haystack.includes(term));
    return make("div", { class: `child-topic ${featured ? "featured" : ""}` }, [
      make("strong", { text: label }),
      make("span", {
        text: `${child.event_count || 0} linked L1 events - ${topicDescription(label)}`,
      }),
    ]);
  });

  q("#topicStory").className = "topic-story";
  q("#topicStory").replaceChildren(
    make("div", { class: "l3-panel" }, [
      make("div", { class: "badge-row" }, [
        badge("L3 topic family", "l3"),
        badge(`${children.length} child L2`, "l2"),
        badge(`${family.event_count || 0} L1 events`, "l1"),
      ]),
      make("h2", { text: family.label || "audio acquisition and signal processing" }),
      make("div", { class: "id-line", text: family.l3_id || "" }),
      make("p", {
        class: "state",
        text: "This topic family exists before any user query. It is a navigation layer over durable child L2 topic states, not a summary generated at answer time.",
      }),
      make("div", { class: "topic-memory-rule" }, [
        make("strong", { text: "Query-time role" }),
        make("span", { text: "L3 orients retrieval; L1 evidence still grounds factual claims." }),
      ]),
    ]),
    make("div", { class: "children-panel" }, [
      make("div", { class: "children-header" }, [
        make("h2", { text: "Child L2 topic states under the family" }),
        badge("query-ready memory", "teal"),
      ]),
      make("div", { class: "children-grid" }, childNodes),
    ]),
  );
}

function renderEvidenceSeed(seed) {
  return make("div", { class: "evidence-item" }, [
    make("strong", { text: `${seed.meeting_id || ""} - ${seed.obj_id || ""}` }),
    make("span", {
      class: "evidence-meta",
      text: `${seed.type || "memory"} | score ${Number(seed.score || 0).toFixed(3)} | importance ${Number(seed.importance || 0).toFixed(2)}`,
    }),
    make("p", { text: preview(seed.content || seed.evidence, 175) }),
  ]);
}

function renderTopicItem(topic) {
  const meta = [
    topic.parent_l3_label || topic.parent_l3_id || "unpromoted L2",
    `${topic.selected_event_count || 0} selected`,
    `${topic.omitted_event_count || 0} omitted`,
  ].filter(Boolean).join(" | ");
  const text = topic.evolution_summary || topic.current_state || (topic.timeline_digest || [])
    .map((event) => event.summary || event.content)
    .filter(Boolean)
    .join(" ");
  return make("div", { class: "topic-item" }, [
    make("strong", { text: topic.label || topic.l2_id || "L2 topic" }),
    make("span", { class: "topic-meta", text: meta }),
    make("p", { text: preview(text, 220) }),
  ]);
}

function renderEvolutionStrip(seeds) {
  const order = ["Bmr001", "Bmr002", "Bmr005", "Bmr011", "Bmr016"];
  const available = new Set((seeds || []).map((seed) => seed.meeting_id).filter(Boolean));
  const dates = order.filter((item) => available.has(item));
  const fallback = [...available].slice(0, 4);
  const values = dates.length ? dates : fallback;
  return make("div", { class: "evolution-strip" }, [
    make("strong", { text: "Cross-meeting evidence path" }),
    make("div", { class: "date-chip-row" }, values.map((value) => badge(value, "l1"))),
  ]);
}

function renderSiblingNavigation(data) {
  const focusedFamily = ((data.global_topic_map || {}).l3_families || [])[0] || {};
  const children = (focusedFamily.child_l2 || [])
    .map((child) => child.label || child.l2_id)
    .filter(Boolean)
    .slice(0, 5);
  if (!children.length) return null;
  return make("div", { class: "sibling-panel" }, [
    make("strong", { text: "L3 sibling navigation" }),
    make("span", { text: "Nearby child L2 topics stay visible as navigation context." }),
    make("div", { class: "sibling-chip-row" }, children.map((name) => badge(name, "l2"))),
  ]);
}

function promptPreview(text) {
  const lines = String(text || "")
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .slice(0, 22);
  return lines.join("\n");
}

function renderTraceStory(data) {
  const seeds = (data.l1_evidence_seeds || []).slice(0, 5);
  const topics = (data.l2_evolution_context || []).slice(0, 3);
  const l3 = (data.l3_navigation || [])[0];
  const l3Badge = l3 ? badge(`L3: ${l3.label || l3.l3_id}`, "l3") : badge("L3 navigation", "l3");

  q("#traceStory").className = "trace-story";
  q("#traceStory").replaceChildren(
    make("div", { class: "context-column l1" }, [
      make("div", { class: "column-title" }, [
        make("h2", { text: "1. L1 Evidence Seeds" }),
        badge(`${seeds.length} shown`, "l1"),
      ]),
      make("div", { class: "id-line", text: "source-grounded objects selected first" }),
      renderEvolutionStrip(seeds),
      make("div", { class: "evidence-list" }, seeds.map(renderEvidenceSeed)),
    ]),
    make("div", { class: "context-column l2" }, [
      make("div", { class: "column-title" }, [
        make("h2", { text: "2. L2 / child-L2 evolution" }),
        l3Badge,
      ]),
      make("div", { class: "id-line", text: "topic context is expanded only after L1 grounding" }),
      make("div", { class: "topic-list" }, topics.map(renderTopicItem)),
      renderSiblingNavigation(data),
    ]),
    make("div", { class: "context-column prompt" }, [
      make("div", { class: "column-title" }, [
        make("h2", { text: "3. Formatted prompt context" }),
        badge("actual injected context", "teal"),
      ]),
      make("div", {
        class: "prompt-note",
        text: "The model receives a compact trace: evidence first, then topic evolution and L3 navigation.",
      }),
      make("pre", { class: "prompt-box", text: promptPreview(data.formatted_prompt_context) }),
    ]),
  );
}

function renderComparisonStory() {
  const cards = [
    {
      cls: "full",
      title: "Full Context",
      number: "All transcript",
      points: [
        "Injects nearly everything into the prompt",
        "High token cost and weak inspectability",
        "Good recall on small corpora, but noisy at scale",
      ],
      takeaway: "Expensive brute force context.",
    },
    {
      cls: "rag",
      title: "Traditional RAG",
      number: "Top-k chunks",
      points: [
        "Finds local transcript snippets",
        "Can miss why a decision evolved over meetings",
        "Hard to see topic lifecycle from isolated chunks",
      ],
      takeaway: "Cheap, but fragmented.",
    },
    {
      cls: "layered",
      title: "Layered Memory",
      number: "L1 + L2 + L3",
      points: [
        "Starts from L1 evidence seeds",
        "Adds L2 topic state and timeline evolution",
        "Uses L3 as navigation, not unsupported evidence",
      ],
      takeaway: "Evidence-grounded and evolution-aware.",
    },
  ];

  q("#comparisonStory").replaceChildren(...cards.map((item) =>
    make("div", { class: `comparison-card ${item.cls}` }, [
      make("div", { class: "badge-row" }, [
        badge(item.cls === "layered" ? "our system" : "baseline", item.cls === "layered" ? "teal" : ""),
      ]),
      make("h2", { text: item.title }),
      make("div", { class: "big-number", text: item.number }),
      make("ul", {}, item.points.map((point) => make("li", { text: point }))),
      make("div", { class: "takeaway", text: item.takeaway }),
    ])
  ));
}

async function init() {
  try {
    const [topics, trace] = await Promise.all([
      api("/api/topics/l3?dataset=icsi"),
      api(`/api/retrieval/trace?dataset=icsi&query=${encodeURIComponent(QUERY)}&retrieval_mode=lexical&no_llm=true&include_debug=false&budget_profile=observatory_paper_trace&max_context_chars=0`),
    ]);
    renderTopicStory(topics);
    renderTraceStory(trace);
    renderComparisonStory();
  } catch (error) {
    const message = make("div", { class: "error-card", text: `Could not load presentation data: ${error.message}` });
    q("#topicStory").replaceChildren(message.cloneNode(true));
    q("#traceStory").replaceChildren(message.cloneNode(true));
    renderComparisonStory();
  }
}

init();
