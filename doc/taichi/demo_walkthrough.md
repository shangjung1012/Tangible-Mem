# Demo Walkthrough

This walkthrough is the recommended Section 5 story and live demo flow.

## Demo Question

```text
Why not feed the full transcript directly, and why split it into segments / idea units?
```

Use the Grace corpus for the cleanest walkthrough. ICSI can be shown later as
evidence that the same inspection machinery can operate on a larger non-Grace
dataset.

## Storyline

1. Start with the question.

   The user asks a rationale/evolution question about the transcript processing
   pipeline. This is intentionally not a simple keyword lookup.

2. Show L1 evidence seeds.

   Retrieval begins with source-grounded L1 evidence. The demo should highlight
   evidence from meetings around the segment / idea-unit discussion, such as
   0422, 0429, and 0506 when available in the trace.

   Message to say:

   > The answer is grounded first in source evidence, not a generated topic
   > summary.

3. Show L2 / child-L2 topic evolution.

   The L1 seeds bring in topic context. This is where the system can show that
   the discussion evolved from full-transcript or turn-based update concerns
   toward segment and idea-unit extraction.

   Message to say:

   > L2 is not another answer. It is the topic state that explains how related
   > evidence changed across meetings.

4. Show L3 navigation.

   The parent L3 topic family shows that this rationale belongs to a broader
   transcript segmentation / idea-unit coverage family. Emphasize that L3 is
   navigation context, not standalone evidence.

   Message to say:

   > L3 helps the user understand where this topic sits in the larger memory
   > structure, but the factual grounding still comes from L1.

5. Show formatted prompt context.

   This is the most direct way to demonstrate inspectable retrieval. The user can
   see what would actually be passed to the answer model.

   Message to say:

   > The retrieval trace makes the model context reviewable before we ask the
   > model to answer.

6. Show object detail and sidecar correction.

   Open one L1 object. Show content, evidence, topic links, and importance. Then
   show that corrections are written as sidecar feedback rather than overwriting
   raw evidence.

   Message to say:

   > Human correction becomes an auditable signal, not a destructive edit.

## Comparison Framing

Use this concise comparison:

- Full Context injects everything. It is complete but expensive and opaque.
- Traditional RAG retrieves local chunks. It is compact but can fragment topic
  evolution.
- Layered Memory starts from L1 evidence and adds L2/L3 context. It is designed
  for inspection and topic-level sensemaking.

## What Not To Say

- Do not claim the system always beats full context.
- Do not claim L2/L3 topics are perfect.
- Do not claim this is a completed user study.
- Do not claim optimization v2 has replaced canonical artifacts.
