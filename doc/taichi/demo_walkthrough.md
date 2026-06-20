# Demo Walkthrough

This walkthrough is the recommended Section 5 story and live demo flow.

## Demo Question

```text
What context about delay-and-sum beamforming and close microphones should carry over to later audio processing discussions?
```

Use the ICSI BMR corpus for the paper walkthrough. Grace remains useful as an
internal sanity check, but the paper demo should avoid a self-referential memory
system example.

## Storyline

1. Start with the question.

   The user asks a rationale/carryover question about audio-processing context.
   This is intentionally not a simple keyword lookup: the system must connect
   close microphones, delay-and-sum beamforming, and later audio-processing
   discussions.

2. Show L1 evidence seeds.

   Retrieval begins with source-grounded L1 evidence. The demo should highlight
   evidence from BMR meetings, such as Bmr001 and Bmr011, where microphone
   placement, beamforming, close-talking microphones, and audio-processing
   constraints appear in source-grounded L1 objects.

   Message to say:

   > The answer is grounded first in source evidence, not a generated topic
   > summary.

3. Show L2 / child-L2 topic evolution.

   The L1 seeds bring in topic context. This is where the system can show that
   evidence about beamforming and microphone setup belongs to durable topics
   such as `audio processing`, `close talking microphone`, and `hardware
   limitation`.

   Message to say:

   > L2 is not another answer. It is the topic state that explains how related
   > evidence changed across meetings.

4. Show L3 navigation.

   The parent L3 topic family shows that this rationale belongs to the broader
   `audio acquisition and signal processing` family. Emphasize that L3 is
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
