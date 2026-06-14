# ICSI Revised Held-Out Evaluation Interpretation

This report is a no-LLM retrieval/evidence comparison. It does not call Gemini or Vertex, and it does not claim final answer quality.

## Inputs

- Source corpus: `optimization/reports/icsi_bmr_full_completed29_eval_pack_20260614/source_share_mem`
- Optimization v2 run: `optimization/runs/icsi_bmr_full_completed29_v2_20260614`
- Revised query pack: `optimization/reports/icsi_bmr_full_completed29_eval_pack_revised_20260614/approved_revised_heldout_eval_queries.jsonl`
- Query count: `20`

## Main Results

| Strategy | Expected L1 recall | Avg context tokens | Avg selected L1 |
|---|---:|---:|---:|
| Full context L1 | 1.0 | 575199.0 | 4715.0 |
| RAG lexical top-20 | 0.5583 | 2369.95 | 20.0 |
| Optimization v2 layered | 0.8958 | 7358.35 | 60.0 |

Optimization v2 also achieved:

- expected L2 hit rate: `1.0`
- expected L2 semantic hit rate: `1.0`
- expected L3 hit rate: `1.0`
- expected L3 semantic hit rate: `1.0`

## What Changed In The Revised Pack

The original 20-question held-out pack had 7 questions marked `revise` during agent pre-review. This revision:

- rewrote those 7 questions to better match their evidence scope;
- removed `L1-Bmr002-239` from q006 because it was process noise;
- removed `L1-Bmr002-114` from q005 because it was only a narrow free-tool uncertainty rather than core annotation-tool workflow evidence;
- kept held-out trigger objects out of expected answer evidence.

The revised 20-question optimization v2 retrieval score improved from `0.7875` to `0.8958` average expected L1 recall under the default top-60 evidence budget.

## Token Sensitivity

A no-LLM sensitivity check was run for optimization v2 by varying only the L1 evidence budget:

| Layered top-k L1 | Expected L1 recall | Avg context tokens |
|---:|---:|---:|
| 20 | 0.5583 | 2430.4 |
| 40 | 0.7958 | 4920.5 |
| 60 | 0.8958 | 7358.35 |
| 80 | 0.9083 | 9717.25 |
| 100 | 0.9083 | 12143.55 |

The top-60 setting is the current default because it preserves nearly all of the top-80 recall while saving about `2.36k` average context tokens. Top-100 adds cost without recall gain.

## Remaining Weak Cases

Six questions still miss at least one exact expected L1 at top-60:

- q001 resource allocation: `0.75`
- q003 microphone signal processing / beamforming: `0.5`
- q006 acoustic model training / digit-reading automation: `0.6667`
- q009 meeting recorder: `0.75`
- q010 far-field microphone data: `0.5`
- q012 digital audio file handling: `0.75`

In all six cases, topic-level retrieval remained correct: L2/L3 exact or semantic hits stayed at `1.0`. The remaining gap is exact-L1 coverage, not topic-family discovery.

## Interpretation

Full context is the upper-bound evidence condition, but it is extremely large: about `575k` estimated context tokens for the source-side L1 evidence.

RAG lexical top-20 is compact, but it misses many expected L1 objects and averages only `0.5583` expected L1 recall.

Optimization v2 layered retrieval is the best current tradeoff: it uses more context than RAG (`~7.4k` tokens), but it retrieves much more expected evidence (`0.8958`) and consistently recovers the expected L2/L3 topic structure.

## Caveat

This is not final answer scoring. A paid LLM answer-quality run is still required before claiming final generated-answer superiority over RAG or full context.
