# TAICHI Figure Inventory

This inventory maps the current paper-ready artifacts to Sections 3-5. It is
intended to keep the HCI paper claims aligned with evidence we can actually
show in the Memory Observatory UI.

## Figure Set

| File | Suggested section | Role | Main claim supported |
|---|---|---|---|
| `doc/taichi/figures/tangible_mem_teaser.png` | Figure 1 / teaser | Conceptual teaser figure | Tangible Mem turns long-term meeting memory into layered, inspectable objects: L1 evidence cards, L2 topic states, L3 topic families, Memory Observatory inspection, sidecar feedback, and answer context. |
| `doc/taichi/figures/memory_observatory_system_overview.png` | Section 3 | System overview figure | The system treats memory as an inspectable pipeline from transcript evidence to topic context, retrieval trace, and sidecar correction. |
| `doc/taichi/screenshots/observatory_presentation_icsi.png` | Section 5 | Walkthrough composite | The ICSI demo can show topic memory before the query, L1-first retrieval, L2/L3 context, and strategy comparison in one sequence. |
| `doc/taichi/screenshots/observatory_trace_icsi_focused.png` | Section 4.2 | Paper-focused Retrieval Trace figure | The UI exposes the inspectable retrieval flow as four readable panels: query/plan, L1 evidence, L2/L3 topic context, and formatted prompt context. |
| `doc/taichi/screenshots/observatory_trace_icsi_audio_processing.png` | Backup / appendix | Full Retrieval Trace screenshot | The complete UI trace shows all retrieved evidence, selected L2/child-L2 context, L3 navigation, and formatted prompt context. |
| `doc/taichi/screenshots/observatory_topic_observatory_icsi.png` | Section 4.3 | Topic Observatory screenshot | Reviewers can inspect L3 topic families, child L2 states, timeline events, linked L1 evidence, and oversized topic flags. |
| `doc/taichi/screenshots/observatory_memory_explorer_icsi.png` | Section 4.1 or 4.4 | Memory Explorer screenshot | Reviewers can inspect object-level content, evidence, topic links, and feedback history without editing raw evidence. |

## Final Paper Selection

Use these five figures for the current TAICHI draft:

1. **Conceptual teaser**: `figures/tangible_mem_teaser.png`
   - Figure 1 / teaser.
   - Main role: make the paper contribution legible before readers enter the
     body text.
2. **System overview**: `figures/memory_observatory_system_overview.png`
   - Section 3.
   - Main role: explain the pipeline and interface surfaces.
3. **Focused Retrieval Trace**: `figures/observatory_trace_icsi_focused.png`
   - Section 4.
   - Main role: show inspectable query-time context assembly.
4. **Topic Observatory + Memory Explorer pair**:
   `figures/observatory_topic_observatory_icsi.png` and
   `figures/observatory_memory_explorer_icsi.png`
   - Section 4.
   - Main role: show topic-level and object-level inspection.
5. **ICSI walkthrough composite**: `figures/observatory_presentation_icsi.png`
   - Section 5.
   - Main role: show the 70-second end-to-end demo story.

Keep `observatory_trace_icsi_audio_processing.png` as appendix or backup
evidence. It is too tall for the main two-column body.

## Recommended Primary Story

Use the ICSI BMR audio-processing walkthrough as the paper example:

```text
What context about delay-and-sum beamforming and close microphones should carry over to later audio processing discussions?
```

Why this example is better than the older Grace idea-unit example:

- It avoids using the system's own memory-design meetings as the main example.
- It shows optimization v2 topic surfaces on an external meeting corpus.
- It makes the L1/L2/L3 distinction concrete: specific microphone and
  beamforming evidence grounds the answer, while L2/L3 provide topic evolution
  and navigation.

## Claims These Figures Can Support

- The system provides an inspectable retrieval trace rather than hiding context
  assembly behind a final answer.
- L1 evidence is visible as source-grounded memory objects.
- L2 and child-L2 topic context can be inspected as topic state and timeline
  events.
- L3 is displayed as navigation context, not standalone factual evidence.
- Corrections are represented as sidecar signals rather than destructive edits
  to raw memory evidence.

## Claims To Avoid Or Phrase Conservatively

- Do not claim the generated topic hierarchy is always correct.
- Do not claim users have empirically improved memory quality unless a user
  study or walkthrough data is added.
- Do not claim final answer quality beats RAG or full context from these UI
  screenshots alone.
- Do not claim optimization v2 has replaced all canonical artifacts; for the
  paper, it is enough to say the ICSI demo uses the optimization v2 topic
  surface while the system keeps canonical artifacts safe.

## Open Paper Tasks

- Select one or two figures for the main paper body; move the rest to appendix
  or presentation backup if page space is tight.
- Use the focused trace figure in the main body when page space is tight; keep
  the full trace screenshot as backup evidence or appendix material.
- Add figure captions that emphasize interaction affordances rather than
  algorithmic implementation details.
