# Sections 3-5 Outline

## Section 3: Design Goals and System Overview

Target length: 1-1.25 pages.

Purpose: explain why an inspectable memory interface is needed before describing
implementation details.

Recommended subsections:

1. `Design Goals for Inspectable AI Memory`
2. `Layered Memory as an Interaction Substrate`
3. `Memory Observatory Overview`

Design goals:

- `DG1: Preserve evidence traceability`  
  Every memory item should remain connected to source meeting evidence.

- `DG2: Expose retrieval as an inspectable process`  
  Users should see how answer context is assembled, not only the final answer.

- `DG3: Support topic-level sensemaking across meetings`  
  Long-term memory should expose topic evolution instead of isolated chunks.

- `DG4: Enable non-destructive human correction`  
  Users can correct importance or feedback without overwriting raw evidence.

Figure needed:

- System overview: transcript -> L1 evidence -> L2 topic context -> L3 topic
  family -> retrieval trace / explorer / feedback.

## Section 4: Implementation

Target length: 2-2.5 pages.

Purpose: describe implemented interaction mechanisms, not every algorithmic
detail.

Recommended subsections:

1. `Evidence-Grounded Memory Representation`
2. `Inspectable Retrieval Trace`
3. `Memory Explorer and Topic Observatory`
4. `Sidecar Feedback and Human Correction Workflow`

Key implementation points:

- L1 objects store content, evidence, meeting metadata, importance, and topic
  hints.
- L2 groups recurring evidence-backed topic context.
- L3 organizes oversized topic groups into navigable topic families.
- Retrieval Trace shows query, L1 evidence seeds, matched L2/child-L2 context,
  parent L3 navigation, selected timeline events, and final formatted context.
- Memory Explorer supports object-level inspection.
- Topic Observatory supports topic-level inspection.
- Sidecar feedback stores human correction without mutating raw L1 evidence.

Figures/screenshots needed:

- Retrieval Trace screenshot.
- Topic Observatory screenshot.
- Memory Explorer object detail screenshot.
- Feedback editor or effective/canonical importance example.

Implementation details that should stay compact:

- L2 scoring formula.
- L3 promotion threshold.
- lexical/hybrid ranking internals.
- exact token budgets.

These can be summarized and moved to appendix.

## Section 5: Use Case Walkthrough

Target length: 1-1.25 pages.

Purpose: show one end-to-end interaction that makes the HCI contribution
concrete.

Recommended walkthrough query:

```text
Why not feed the full transcript directly, and why split it into segments / idea units?
```

Walkthrough sequence:

1. User starts from a rationale question.
2. Retrieval Trace surfaces L1 evidence from relevant meetings.
3. L2 / child-L2 context shows topic evolution across meetings.
4. L3 topic family gives navigation context rather than evidence.
5. User opens an L1 object to inspect source evidence.
6. User adjusts importance or flags a correction through sidecar feedback.

Recommended narrative:

The system does not ask the user to trust a hidden retrieval step. It turns the
retrieval process into an inspectable artifact: users can see which evidence was
selected, which topic context was added, which events were omitted, and how a
correction would be recorded without changing raw evidence.
