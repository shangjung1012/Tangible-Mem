# Multi-Agent L1 0422 Evaluation Notes

This note records the concrete checks from the `0422` Grace transcript run used
to validate multi-agent L1 segmentation, boundary refinement, viewpoint
recurrence, and importance calibration.

## Source

- Transcript: `meeting_recording/transcript/grace/0422.txt`
- Line count: `183`
- Model used in live checks: `gemini-2.5-pro`
- Original full run artifact directory:
  `/tmp/lt_ultimate_0422_ma_logs_v4/20260504T194645Z_0422_multi_agent`

The raw `/tmp` artifacts are not committed. This document keeps the reviewable
results in the repository.

## Boundary Question

The main question was whether fixed windows create artificial semantic
boundaries, especially around:

- `80/81`
- `160/161`

The answer from the checks is:

> Fixed windows still influence the first segmentation pass, but cross-window
> boundary refinement prevents them from becoming final semantic boundaries.

## Original Window-Based Segments

The original multi-agent run produced these relevant segments:

```text
1-13     Introduction to Tool Calling for Memory Updates
14-32    Alternative Approach: Pre-processing into Cohesive Idea Units
33-44    Comparison of Dynamic vs. Pre-processed Segmentation
45-64    Efficiency and Benefits of Iterative Tool Calling for Non-Sequential Ideas
65-80    Mechanics of How the LLM Dynamically Determines Chunk Size
81-96    Proposing a dynamic segmentation method using information entropy
97-111   Defining the structure of long-term memory objects
112-128  Comparing the structures of short-term and long-term (L1-L3) memory
129-141  Debating the necessity and core differences between short-term and long-term memory
142-160  Forgetting / information decay + evaluation/demo strategy
161-183  Project demo narrative + forgetting mechanisms
```

Coverage was complete:

```text
segment coverage rate: 1.0
uncovered transcript lines: 0
```

However, `65-80 / 81-96` and `142-160 / 161-183` were both near fixed window
boundaries, so they needed direct checks.

## Direct Shifted-Window Checks

### Direct `120-183` Segmentation

When `120-183` was segmented directly, the model did not preserve the old
`160/161` split:

```text
120-133  Clarifying long-term vs. short-term memory structures
134-156  Developing the forgetting mechanism as a core advantage
157-172  Planning a demonstration using historical meeting data
173-183  Framing the project narrative and discussing selective forgetting
```

This showed that `160/161` was an artificial window boundary.

### Direct `60-110` Segmentation

When `60-110` was segmented directly, the model did not preserve the old
`80/81` split:

```text
raw:
60-75    Clarifying the dynamic chunking mechanism via LLM
76-86    Proposing an information entropy-based segmentation method
87-96    Analyzing computational trade-offs of dynamic segmentation
97-102   Discussing output format and project evaluation strategy
103-110  Defining the structure of a long-term memory object

after deterministic coarsening:
60-75    Dynamic chunking mechanism
76-96    Entropy segmentation + computational trade-offs
97-110   Output format / evaluation strategy + memory object structure
```

This showed that `80/81` was also somewhat boundary-sensitive.

## Boundary Refinement Result

The pipeline now runs cross-window boundary refinement before idea-unit
extraction. It checks adjacent segments from different windows and, when there
is enough continuity signal, re-segments the joined core span with extra
lookback/lookahead context.

Current refinement settings:

```text
boundary transcript window: 6 lines
boundary refinement context: 16 lookback + 16 lookahead lines
output clamp: original core span only
```

### Refined `65-96`

Old:

```text
65-80
81-96
```

Refined with context:

```text
65-86  Dynamic text chunking using LLM/function calling + comparison to entropy-style approaches
87-96  Trade-offs and novelty of predicting look-ahead sentence count
```

### Refined `142-183`

Old:

```text
142-160
161-183
```

Refined with context:

```text
142-156  Efficiency of long-term memory with forgetting/decay
157-178  Demo strategy using historical meeting data + project narrative
179-183  Selective forgetting of sensitive information in LLMs
```

## Segment Boundary Conclusion

The accurate claim is:

> The pipeline still uses fixed windows for operational stability, but fixed
> windows are no longer treated as final semantic boundaries.

The stronger claim would be too broad:

> Windowing has no effect on the result.

That is not guaranteed, because the first pass still depends on window scope and
LLM segmentation is context-sensitive. The implemented guarantee is narrower:

- suspicious cross-window segments are detected
- those spans are re-segmented with surrounding context
- the result is recorded in `boundary_refinement.json`
- final `segments.json` contains the refined segments

## Viewpoint And Concept Results

Using the strict viewpoint recurrence reducer on the `0422` verified
candidates:

```text
final L1 objects: 25
unique concept keys: 17
unique viewpoint keys: 8
recurring viewpoint keys: 2
```

Object coverage:

```text
objects with concept key: 18 / 25
objects without concept key: 7 / 25
objects with viewpoint key: 11 / 25
objects without viewpoint key: 14 / 25
```

Concept keys are broader and can support de-duplication:

```text
demo_dataset_strategy: 3
dynamic_tool_calling_read: 2
entropy_literature_review: 1
entropy_segmentation: 2
flat_memory_tree: 1
forgetting_mechanism: 1
global_vector_alternative: 1
idea_unit_grouping: 2
idea_unit_preprocess: 2
l123_hierarchy: 1
memory_object_schema: 1
memory_separation: 1
memory_update_router: 2
rag_baseline_comparison: 4
read_write_memory_update: 1
transcript_preparation: 1
unit_generation_evaluation: 2
```

Viewpoint keys are stricter and are the only keys allowed to trigger recurrence
importance:

```text
compare_memory_architecture_with_rag: 4
compare_unit_generation_baselines: 2
demo_own_meeting_dataset: 2
idea_unit_cross_span_merging: 1
idea_unit_demo_scope: 2
long_term_forgetting_decay: 1
memory_object_schema_fields: 1
short_long_memory_storage_distinction: 2
```

Only two viewpoints formed separated recurrence episodes:

```text
compare_memory_architecture_with_rag
episode_count=2
affected_objects=4
bonus=+0.02
evidence ranges: 100-102, 157-164, 171-174

long_term_forgetting_decay
episode_count=2
affected_objects=1
bonus=+0.02
evidence ranges: 142-146, 148-153, 155-156, 177
```

This is intentionally stricter than concept grouping. Related broad topics do
not automatically become the same recurring viewpoint.

## Importance Distribution

After strict viewpoint identity and lower recurrence bonus:

```text
objects: 25
type distribution: method_change=4, decision=8, todo=7, result=6
min importance: 0.60
max importance: 0.84
average importance: 0.701
objects >= 0.9: 0
objects >= 0.8: 2
objects >= 0.7: 12
```

This is more discriminative than the earlier version, where too many ordinary
objects reached `0.9+`.

## Validation

Commands used before preparing this note:

```bash
uv run python -m unittest discover -s tests
git diff --check
```

Result:

```text
Ran 140 tests ... OK
git diff --check: OK
```
