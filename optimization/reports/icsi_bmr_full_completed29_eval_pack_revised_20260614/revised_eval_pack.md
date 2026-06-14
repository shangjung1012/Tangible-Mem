# Revised ICSI Held-Out Eval Pack

This pack applies the agent pre-review decisions to the original held-out future-meeting questions.
It remains a dry-run evaluation pack: held-out triggers are used only to justify question relevance, not as answer evidence.

## Summary

- total queries: `20`
- accepted unchanged: `13`
- revised: `7`
- removed expected L1 ids: `{'icsi-heldout-q005': ['L1-Bmr002-114'], 'icsi-heldout-q006': ['L1-Bmr002-239']}`
- status: `agent_revised_dry_run_pack_human_review_required`

## Revised Questions

### icsi-heldout-q001 `evidence_lookup`

- status: `accepted`
- query: What concrete source-side evidence did the ICSI BMR meetings contain about resource allocation?
- expected L1: `L1-Bmr001-052, L1-Bmr002-031, L1-Bmr002-059, L1-Bmr002-060`
- expected L2 labels: `resource allocation`
- expected L3 labels: `project planning and management`

- review reason: Resource allocation is answerable from multiple source-side evidence objects and later meetings clearly revisit responsibility and resource constraints.

### icsi-heldout-q002 `evidence_lookup`

- status: `revised`
- query: What source-side evidence did the BMR meetings contain about disk space constraints and storage decisions?
- expected L1: `L1-Bmr001-085, L1-Bmr001-099, L1-Bmr001-100, L1-Bmr001-158`
- expected L2 labels: `disk space`
- expected L3 labels: `corpus design and data management`

- review reason: Disk space is a valid topic, but all source evidence is from one source meeting, so the evolution wording overstates cross-meeting development.

### icsi-heldout-q003 `decision_rationale`

- status: `revised`
- query: What source-side rationale was discussed for microphone signal processing and beamforming choices?
- expected L1: `L1-Bmr001-046, L1-Bmr001-047, L1-Bmr001-053, L1-Bmr001-056`
- expected L2 labels: `audio processing`
- expected L3 labels: `audio acquisition and signal processing`

- review reason: Audio processing is valid but broad, and exact L1 recall is low. The question should be narrowed to beamforming, microphone processing, or signal processing rationale.

### icsi-heldout-q004 `next_meeting_carryover`

- status: `accepted`
- query: What context about speech recognition should be carried into later BMR meetings?
- expected L1: `L1-Bmr002-203, L1-Bmr002-205, L1-Bmr003-099, L1-Bmr003-228`
- expected L2 labels: `speech recognition`
- expected L3 labels: `asr modeling and evaluation`

- review reason: Speech recognition has strong source evidence, future triggers, perfect retrieval recall, and is a realistic next-meeting carryover question.

### icsi-heldout-q005 `evidence_lookup`

- status: `revised`
- query: Which source-side annotation tool candidates, including Mississippi State tools and XWaves, had been considered for the BMR transcription workflow?
- expected L1: `L1-Bmr002-093, L1-Bmr002-094, L1-Bmr002-095`
- expected L2 labels: `annotation tool`
- expected L3 labels: `annotation and transcription workflow`

- review reason: Annotation tool is meaningful, but the corpus-process wording is too broad for mostly one-meeting source evidence and exact L1 recall is low.

### icsi-heldout-q006 `evidence_lookup`

- status: `revised`
- query: What source-side evidence discussed acoustic model training data and digit-reading automation?
- expected L1: `L1-Bmr002-197, L1-Bmr005-148, L1-Bmr005-168`
- expected L2 labels: `acoustic modeling`
- expected L3 labels: `asr modeling and evaluation`

- review reason: Acoustic modeling is valid, but one expected source object is process-noise about Control-C, so expected evidence should be narrowed before scoring.

### icsi-heldout-q007 `topic_evolution`

- status: `accepted`
- query: Before the held-out meetings, how had audio quality evolved across the ICSI BMR discussions?
- expected L1: `L1-Bmr001-034, L1-Bmr001-042, L1-Bmr001-065, L1-Bmr001-066`
- expected L2 labels: `audio quality`
- expected L3 labels: `audio acquisition and signal processing`

- review reason: Audio quality is well supported by source and held-out evidence and retrieval finds all expected L1 objects.

### icsi-heldout-q008 `next_meeting_carryover`

- status: `revised`
- query: What meeting agenda items were deferred or carried forward in the source-side BMR meetings?
- expected L1: `L1-Bmr002-170, L1-Bmr003-003, L1-Bmr006-294, L1-Bmr006-321`
- expected L2 labels: `meeting agenda`
- expected L3 labels: `project planning and management`

- review reason: Meeting agenda is a real process topic, but it is meta-level and the decision-rationale wording is weaker than an evidence-lookup or carryover formulation.

### icsi-heldout-q009 `next_meeting_carryover`

- status: `accepted`
- query: What context about meeting recorder should be carried into later BMR meetings?
- expected L1: `L1-Bmr001-122, L1-Bmr002-161, L1-Bmr002-162, L1-Bmr002-163`
- expected L2 labels: `meeting recorder`
- expected L3 labels: `project planning and management`

- review reason: Meeting recorder is central to the corpus, has clear source and held-out evidence, and works as a carryover question.

### icsi-heldout-q010 `evidence_lookup`

- status: `revised`
- query: What source-side evidence established far-field microphone data as an important project goal?
- expected L1: `L1-Bmr002-187, L1-Bmr002-198, L1-Bmr002-200, L1-Bmr003-045`
- expected L2 labels: `far field`
- expected L3 labels: `audio acquisition and signal processing`

- review reason: Far-field is important but the corpus-process wording is awkward and exact L1 recall is low; the question should focus on far-field recording decisions.

### icsi-heldout-q011 `evidence_lookup`

- status: `accepted`
- query: What concrete source-side evidence did the ICSI BMR meetings contain about error analysis?
- expected L1: `L1-Bmr003-336, L1-Bmr006-263, L1-Bmr016-079, L1-Bmr016-080`
- expected L2 labels: `error analysis`
- expected L3 labels: `asr modeling and evaluation`

- review reason: Error analysis has clear source-side evidence, future trigger examples, and perfect retrieval recall.

### icsi-heldout-q012 `evidence_lookup`

- status: `revised`
- query: What source-side evidence discussed digital audio file handling, file size, and transcription tooling?
- expected L1: `L1-Bmr001-104, L1-Bmr002-044, L1-Bmr002-046, L1-Bmr002-048`
- expected L2 labels: `audio file`
- expected L3 labels: `corpus design and data management`

- review reason: Audio file is a real topic, but the evolution wording is awkward and exact L1 recall is low. It should be rewritten around digital audio file handling.

### icsi-heldout-q013 `decision_rationale`

- status: `accepted`
- query: What decisions or rationale were established about signal processing before the later BMR meetings revisited it?
- expected L1: `L1-Bmr001-045, L1-Bmr001-054, L1-Bmr001-103, L1-Bmr006-198`
- expected L2 labels: `signal processing`
- expected L3 labels: `audio acquisition and signal processing`

- review reason: Signal processing is strongly supported and the source-side rationale aligns with later held-out triggers.

### icsi-heldout-q014 `next_meeting_carryover`

- status: `accepted`
- query: What context about broadcast news should be carried into later BMR meetings?
- expected L1: `L1-Bmr001-095, L1-Bmr001-098, L1-Bmr006-106, L1-Bmr006-109`
- expected L2 labels: `broadcast news`
- expected L3 labels: `corpus design and data management`

- review reason: Broadcast news is coherent as a carryover topic, with source-side disk-space context and later generalization/training context.

### icsi-heldout-q015 `corpus_process`

- status: `accepted`
- query: What does the source-side BMR corpus reveal about the process or workflow around user interface?
- expected L1: `L1-Bmr003-169, L1-Bmr003-173, L1-Bmr003-182, L1-Bmr003-183`
- expected L2 labels: `user interface`
- expected L3 labels: `annotation and transcription workflow`

- review reason: User interface is a useful corpus-process topic, supported by source-side transcription interface evidence and later UI/tool needs.

### icsi-heldout-q016 `evidence_lookup`

- status: `accepted`
- query: What concrete source-side evidence did the ICSI BMR meetings contain about experimental setup?
- expected L1: `L1-Bmr006-251, L1-Bmr006-252, L1-Bmr006-272, L1-Bmr007-088`
- expected L2 labels: `experimental setup`
- expected L3 labels: ``

- review reason: Experimental setup is answerable from source evidence and later meetings revisit training and experimental-design concerns.

### icsi-heldout-q017 `topic_evolution`

- status: `accepted`
- query: Before the held-out meetings, how had conversational speech evolved across the ICSI BMR discussions?
- expected L1: `L1-Bmr003-096, L1-Bmr013-040, L1-Bmr013-046, L1-Bmr013-048`
- expected L2 labels: `conversational speech`
- expected L3 labels: ``

- review reason: Conversational speech is a strong topic-evolution question with clear source-side ASR and phonetic-analysis evidence.

### icsi-heldout-q018 `decision_rationale`

- status: `accepted`
- query: What decisions or rationale were established about user feedback before the later BMR meetings revisited it?
- expected L1: `L1-Bmr018-173, L1-Bmr021-004`
- expected L2 labels: `user feedback`
- expected L3 labels: ``

- review reason: User feedback is usable for decision/rationale review, especially microphone comfort and later user-facing tool feedback.

### icsi-heldout-q019 `next_meeting_carryover`

- status: `accepted`
- query: What context about digit reading task should be carried into later BMR meetings?
- expected L1: `L1-Bmr002-020, L1-Bmr002-021, L1-Bmr002-022, L1-Bmr002-023`
- expected L2 labels: `digit reading task`
- expected L3 labels: `corpus design and data management`

- review reason: Digit reading task is a strong carryover question with clear source protocol evidence and later workflow changes.

### icsi-heldout-q020 `corpus_process`

- status: `accepted`
- query: What does the source-side BMR corpus reveal about the process or workflow around forced alignment?
- expected L1: `L1-Bmr002-092, L1-Bmr009-098, L1-Bmr009-099, L1-Bmr009-101`
- expected L2 labels: `forced alignment`
- expected L3 labels: `annotation and transcription workflow`

- review reason: Forced alignment has clear source-side workflow evidence and later held-out transcription-method triggers.
