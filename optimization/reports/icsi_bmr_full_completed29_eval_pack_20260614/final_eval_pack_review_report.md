# ICSI Held-Out Eval Pack Review Report

- status: `agent_pre_review_complete_human_review_required`
- total questions reviewed: `20`
- accepted: `13`
- revise: `7`
- reject: `0`

This is an agent pre-review. It is strong enough for an answer-quality dry run, but professor-facing claims still need human approval.

## Accepted Questions

- `icsi-heldout-q001` `evidence_lookup` `resource allocation`: What concrete source-side evidence did the ICSI BMR meetings contain about resource allocation?
- `icsi-heldout-q004` `next_meeting_carryover` `speech recognition`: What context about speech recognition should be carried into later BMR meetings?
- `icsi-heldout-q007` `topic_evolution` `audio quality`: Before the held-out meetings, how had audio quality evolved across the ICSI BMR discussions?
- `icsi-heldout-q009` `next_meeting_carryover` `meeting recorder`: What context about meeting recorder should be carried into later BMR meetings?
- `icsi-heldout-q011` `evidence_lookup` `error analysis`: What concrete source-side evidence did the ICSI BMR meetings contain about error analysis?
- `icsi-heldout-q013` `decision_rationale` `signal processing`: What decisions or rationale were established about signal processing before the later BMR meetings revisited it?
- `icsi-heldout-q014` `next_meeting_carryover` `broadcast news`: What context about broadcast news should be carried into later BMR meetings?
- `icsi-heldout-q015` `corpus_process` `user interface`: What does the source-side BMR corpus reveal about the process or workflow around user interface?
- `icsi-heldout-q016` `evidence_lookup` `experimental setup`: What concrete source-side evidence did the ICSI BMR meetings contain about experimental setup?
- `icsi-heldout-q017` `topic_evolution` `conversational speech`: Before the held-out meetings, how had conversational speech evolved across the ICSI BMR discussions?
- `icsi-heldout-q018` `decision_rationale` `user feedback`: What decisions or rationale were established about user feedback before the later BMR meetings revisited it?
- `icsi-heldout-q019` `next_meeting_carryover` `digit reading task`: What context about digit reading task should be carried into later BMR meetings?
- `icsi-heldout-q020` `corpus_process` `forced alignment`: What does the source-side BMR corpus reveal about the process or workflow around forced alignment?

## Revise Before Final Scoring

- `icsi-heldout-q002` `topic_evolution` `disk space`: Disk space is a valid topic, but all source evidence is from one source meeting, so the evolution wording overstates cross-meeting development.
  - recommended query: What source-side evidence did the BMR meetings contain about disk space constraints and storage decisions?
- `icsi-heldout-q003` `decision_rationale` `audio processing`: Audio processing is valid but broad, and exact L1 recall is low. The question should be narrowed to beamforming, microphone processing, or signal processing rationale.
  - recommended query: What source-side rationale was discussed for microphone signal processing and beamforming choices?
- `icsi-heldout-q005` `corpus_process` `annotation tool`: Annotation tool is meaningful, but the corpus-process wording is too broad for mostly one-meeting source evidence and exact L1 recall is low.
  - recommended query: What annotation tool options and workflow requirements had been discussed before later transcription workflow changes?
- `icsi-heldout-q006` `evidence_lookup` `acoustic modeling`: Acoustic modeling is valid, but one expected source object is process-noise about Control-C, so expected evidence should be narrowed before scoring.
  - recommended query: What source-side evidence discussed acoustic model training data and digit-reading automation?
- `icsi-heldout-q008` `decision_rationale` `meeting agenda`: Meeting agenda is a real process topic, but it is meta-level and the decision-rationale wording is weaker than an evidence-lookup or carryover formulation.
  - recommended query: What meeting agenda items were deferred or carried forward in the source-side BMR meetings?
- `icsi-heldout-q010` `corpus_process` `far field`: Far-field is important but the corpus-process wording is awkward and exact L1 recall is low; the question should focus on far-field recording decisions.
  - recommended query: What source-side evidence established far-field microphone data as an important project goal?
- `icsi-heldout-q012` `topic_evolution` `audio file`: Audio file is a real topic, but the evolution wording is awkward and exact L1 recall is low. It should be rewritten around digital audio file handling.
  - recommended query: What source-side evidence discussed digital audio file handling, file size, and transcription tooling?

## Output Files

- `review_decisions.jsonl`
- `approved_heldout_eval_queries.jsonl`
- `final_eval_pack_review_report.json`
- `final_eval_pack_review_report.md`

## Approved Subset Retrieval Diagnostic

- queries: `13`
- avg expected L1 recall: `0.9615`
- expected L2 hit rate: `1.0`
- expected L2 semantic hit rate: `1.0`
- expected L3 hit rate: `1.0`
- expected L3 semantic hit rate: `1.0`
