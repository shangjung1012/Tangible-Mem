# Long-Term Memory Evaluation Plan

This document defines the evaluation plan for the project demo and final
competition presentation. It is written as an implementation-ready brief for
Codex CLI.

## 1. Evaluation Goal

The evaluation should prove three claims:

1. The memory system is more useful than standard RAG over raw meeting data.
2. Each memory layer has a measurable role: short-term context, L1 evidence,
   L2 topic context, and optional sidecars.
3. Human edits to sidecar or taxonomy state can predictably change the agent's
   retrieved context and final answer without mutating raw L1 evidence.

The main claim is about memory representation and retrieval behavior, not about
which foundation model is strongest.

## 2. Scope

In scope:

- `share_mem/tree.json` as canonical L1 evidence.
- `long_term/l2/l2_index.json` and `long_term/l2/l2_view.json` as active L2
  sources.
- `short_term/short_term_memory.json` as the current short-term state.
- `app/memory_router.py` and `app/memory_context.py::retrieve_memory_context`
  as the short/long routing layer.
- Existing long-term recall path.
- Optional sidecars:
  - `share_mem/l1_quality_index.json`
  - `share_mem/memory_relations_index.json`
  - `share_mem/memory_activity_index.json`

Out of scope for the first evaluation pass:

- New frontend UI.
- Mutating raw L1 evidence objects in `share_mem/tree.json`.
- Treating short-term memory as full meeting history.

## 3. Core Baselines

Use the same answer model across the main comparisons whenever possible. This
keeps the experiment focused on memory method rather than model strength.

### 3.1 Raw Transcript RAG

Retrieve chunks from raw meeting transcripts, then answer with the retrieved
chunks.

Purpose:

- Represents a standard RAG baseline.
- Tests whether L1/L2 memory gives cleaner context than raw transcript chunks.

Expected weakness:

- May retrieve noisy local context.
- May miss cross-meeting continuity.
- May return long chunks that are hard to inspect.

### 3.2 Full Transcript To Gemini

Feed all available transcript text, or the largest practical transcript bundle,
directly to Gemini.

Purpose:

- Represents an expensive full-context / oracle-style baseline.
- Answers the likely judge question: "Why not just put all transcripts into the
  prompt?"

Important naming:

- Do not call this short-term memory.
- Do not call this RAG.
- Call it `Full transcript baseline` or `Full-context transcript baseline`.

Expected tradeoff:

- May perform well when the dataset is small.
- Token cost and latency grow quickly.
- It is less controllable and harder to audit than the memory system.

### 3.3 L1-Only Memory Recall

Retrieve from canonical L1 memory objects only.

Purpose:

- Tests whether distilled L1 evidence is already better than raw transcript RAG.
- Provides a baseline before adding L2 topic context.

Expected weakness:

- Can be fragmented.
- May miss the larger topic-level synthesis that L2 provides.

### 3.4 L1 + L2 Memory Recall

Retrieve L1 hits, then expand through `l2_index.json` and `l2_view.json` to add
compact upward topic context.

Purpose:

- Main long-term memory condition.
- Tests whether L2 improves synthesis, compactness, and recall usefulness.

Expected strength:

- Keeps grounded L1 evidence while adding topic-level context.
- Should be more compact than raw transcript or full transcript baselines.

### 3.5 Short-Term + Long-Term Hybrid

Use short-term context only for the current interaction or current working
memory, then combine it with long-term L1 + L2 recall.

Purpose:

- Represents the intended final agent behavior.
- Tests whether current local context and long-term project memory complement
  each other.

Important constraint:

- Short-term memory must not receive all historical meetings. If it does, it
  becomes a full-context baseline instead of short-term memory.
- The current checked-in short-term state is a compact unit store updated from
  share_mem snapshots. Units age out after being missed for two meetings.
- The retrieval router should decide `short_term`, `long_term`, or `both`.
  Ambiguous questions can use both, but recent-status questions should not
  always force long-term recall.

## 4. Optional Model Robustness Check

GPT can be added as a secondary robustness check, but it should not be the main
experiment unless there is enough time.

Recommended main setup:

- Same model + different memory methods.

Optional robustness setup:

- Gemini + Raw Transcript RAG
- Gemini + L1 + L2 Memory
- GPT + Raw Transcript RAG
- GPT + L1 + L2 Memory

Interpretation:

- If both Gemini and GPT show the same trend, the memory architecture is likely
  contributing beyond model choice.
- If only one model improves, report it as a model interaction instead of a
  universal memory result.

## 5. Experiment 1: Memory Method Comparison

Question:

- Does the proposed memory system outperform standard retrieval or transcript
  stuffing for meeting-memory tasks?

Conditions:

1. Raw Transcript RAG
2. Full Transcript To Gemini
3. L1-Only Memory Recall
4. L1 + L2 Memory Recall
5. Short-Term + Long-Term Hybrid

Recommended minimum if time is short:

1. Raw Transcript RAG
2. Full Transcript To Gemini
3. L1 + L2 Memory Recall
4. Short-Term + Long-Term Hybrid

Primary metrics:

- Answer correctness.
- Gold evidence hit rate.
- Context precision.
- Citation faithfulness.
- Prompt token count.
- Latency.

Expected story:

- Full transcript may be strong on correctness for small data, but it should be
  costly and hard to control.
- Raw transcript RAG should be cheaper than full transcript but noisier.
- L1 + L2 memory should provide shorter, more inspectable context with strong
  evidence grounding.

## 6. Experiment 2: System Ablation

Question:

- Which parts of the memory architecture are responsible for the final answer
  quality?

Conditions:

1. No memory / current query only.
2. Short-Term only.
3. Long-Term L1 only.
4. Long-Term L1 + L2.
5. Long-Term L1 + L2 + sidecars, if sidecars are wired into recall ranking.
6. Short-Term + Long-Term L1 + L2.

Recommended minimum if time is short:

1. Short-Term only.
2. Long-Term L1 only.
3. Long-Term L1 + L2.
4. Short-Term + Long-Term L1 + L2.

Definitions:

- Short-Term only means current meeting or current conversation window only.
- Long-Term L1 only means retrieved L1 evidence without L2 expansion.
- Long-Term L1 + L2 means L1 hits plus upward topic context from L2.
- Hybrid means current local context plus long-term recall.

Expected story:

- Short-Term only should do well on recent-context questions and poorly on
  cross-meeting questions.
- L1 only should find evidence but may be fragmented.
- L1 + L2 should improve synthesis and answer focus.
- Hybrid should perform best when the user question depends on both the current
  interaction and older project memory.

## 7. Experiment 3: HITL Control Test

Question:

- If a human manually edits sidecar or taxonomy state, does the agent's
  retrieval context and answer change in the intended direction?

This experiment demonstrates controllability and auditability.

### 7.1 Activity Edit

Manual change:

- Mark an old relevant L1 as `active` or `reactivated` in activity sidecar.

Expected effect:

- The L1 should be easier to retrieve or rank higher.
- The final answer should mention or cite it when relevant.

Record:

- Retrieved L1 ids before edit.
- Retrieved L1 ids after edit.
- Answer difference.
- Whether the changed answer is better supported.

### 7.2 Quality Edit

Manual change:

- Mark a suspicious L1 as `weak` or lower confidence in quality sidecar.

Expected effect:

- The system should avoid relying on that L1, rank it lower, or describe it more
  cautiously if it is still included.

Record:

- Whether the weak L1 appears in retrieved context.
- Whether the answer still cites it.
- Whether answer wording becomes more cautious.

### 7.3 L2 Assignment Or Promotion Edit

Manual change:

- Split an oversized L2 into child L2 topics through the L3 promotion sidecar or
  equivalent taxonomy edit.

Expected effect:

- Topic synthesis questions should receive more focused L2 context.
- The answer should mix fewer unrelated subtopics.

Example:

- Before: one large `transcript segmentation and idea unit coverage` L2.
- After: child L2 topics such as:
  - `transcript segmentation`
  - `idea unit coverage`
  - `evidence coverage`

Record:

- L2 context before edit.
- L2 context after edit.
- Answer focus before and after edit.

## 8. Evaluation Question Set

Prepare a fixed question set with gold answers and gold evidence ids.

Recommended categories:

### 8.1 Recent Context Questions

Answer should be available in the current meeting or current interaction.

Expected winner:

- Short-Term only or Hybrid.

### 8.2 Cross-Meeting Recall Questions

Answer requires a decision, finding, or open issue from older meetings.

Expected winner:

- Long-Term L1 + L2 or Hybrid.

### 8.3 Topic Synthesis Questions

Answer requires summarizing progress across many L1 objects under a topic.

Example:

- "What is our current design direction for idea unit segmentation?"

Expected winner:

- L1 + L2 or Hybrid.

### 8.4 Conflict Or Update Questions

Answer requires knowing that an older item was resolved, superseded, or
reactivated.

Expected winner:

- Memory with relation/activity sidecars, if wired into recall behavior.

### 8.5 Irrelevant Suppression Questions

Question has lexical overlap with administrative or local context, but the
correct answer should focus on durable project memory.

Expected winner:

- L1 + L2 with filtering and sidecar support.

## 9. Required Gold Labels

For each evaluation question, create a row with:

- `question_id`
- `question`
- `category`
- `expected_answer`
- `gold_meeting_ids`
- `gold_l1_obj_ids`
- `gold_l2_ids`, if applicable
- `notes`

The gold labels are necessary because correctness alone is too subjective. The
evaluation should verify whether the system retrieved the evidence that a human
expects it to use.

## 10. Suggested Metrics

### 10.1 Answer Correctness

Human score from 0 to 2:

- 0: wrong or unsupported.
- 1: partially correct.
- 2: correct and complete.

### 10.2 Gold Evidence Hit Rate

Whether retrieved context includes expected L1 evidence.

Simple formula:

```text
hit_rate = retrieved_gold_l1_count / total_gold_l1_count
```

### 10.3 Context Precision

How much retrieved context is actually relevant.

Simple formula:

```text
precision = relevant_retrieved_items / total_retrieved_items
```

### 10.4 Citation Faithfulness

Human score from 0 to 2:

- 0: answer claims are not supported by retrieved context.
- 1: partially supported.
- 2: clearly supported by cited evidence.

### 10.5 Token Cost

Record prompt tokens or approximate context length for every condition.

This is important for comparing against full transcript baseline.

### 10.6 Latency

Record elapsed seconds from query to answer.

## 11. Recommended Demo Narrative

Use this framing during the competition:

> We compare against raw transcript RAG and a full-transcript Gemini baseline.
> Full transcript prompting can work on small history, but it is expensive,
> hard to audit, and hard to manually correct. Our system stores immutable L1
> evidence, builds L2 topic context, and keeps quality, relation, and activity
> edits in sidecars. The ablation shows that L1 gives grounded evidence, L2
> improves synthesis, and the hybrid system combines current context with
> long-term project memory. The HITL test shows that human edits to sidecar or
> taxonomy state predictably change what the agent retrieves and says, without
> rewriting raw evidence.

## 12. Implementation Checklist For Codex CLI

1. Create a small evaluation question file with the schema in section 9.
2. Implement or reuse runners for each condition:
   - Raw Transcript RAG.
   - Full Transcript To Gemini.
   - L1-Only Memory Recall.
   - L1 + L2 Memory Recall.
   - Short-Term + Long-Term Hybrid.
3. Ensure every run logs:
   - query
   - condition
   - retrieved context ids
   - retrieved context text summary
   - answer
   - token count or context length
   - latency
4. Add a scoring script or manual scoring template for:
   - correctness
   - evidence hit rate
   - context precision
   - citation faithfulness
5. Add before/after fixtures for HITL sidecar or taxonomy edits.
6. Generate a final markdown or CSV result table for the presentation.

## 13. Priority Order

If time is limited, implement in this order:

1. Fixed evaluation question set with gold L1 ids.
2. L1 + L2 memory condition.
3. Raw Transcript RAG baseline.
4. Full Transcript To Gemini baseline.
5. Short-Term + Long-Term Hybrid.
6. L1-only ablation.
7. HITL before/after test.
8. Optional GPT robustness check.

## 14. Key Risk

If the dataset is too small, full transcript prompting may look as good as or
better than the memory system. This should be handled by reporting token cost,
latency, controllability, and auditability, and by including enough multi-meeting
questions for long-term memory to matter.
