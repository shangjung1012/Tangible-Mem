# ICSI Transcript-Span Benchmark Seeds

- status: `annotation_ready_needs_human_review`
- generated at: `2026-06-22T08:21:22Z`
- source boundary: `Bmr023`
- query count: `5`

These rows are annotation-ready seeds, not completed gold labels. A human reviewer must confirm the trigger span, past gold spans, and evidence brief before paper-facing evaluation.

## Fairness Boundary

- Primary gold is original transcript span evidence.
- Generated L1 ids are diagnostic alignment only.
- L2/L3 labels are optional navigation diagnostics, not primary gold.

## Seed Questions

### icsi-span-q001 `carryover_context`

Before the later audio-processing discussion, what earlier context about close microphones and beamforming should the system remember?

- held-out trigger: `Bmr024` lines 357-359
- source gold spans:
  - `Bmr001` lines 42-44: Past meeting discusses close microphones, beamforming, or related audio-channel rationale.
  - `Bmr002` lines 5-7: Past meeting discusses close microphones, beamforming, or related audio-channel rationale.

### icsi-span-q002 `corpus_process`

What earlier context about annotation tools and workflow should carry over when later meetings discuss transcript or annotation work?

- held-out trigger: `Bmr024` lines 22-24
- source gold spans:
  - `Bmr001` lines 673-675: Past meeting discusses annotation tools, transcription workflow, or tool requirements.
  - `Bmr002` lines 378-380: Past meeting discusses annotation tools, transcription workflow, or tool requirements.

### icsi-span-q003 `evidence_lookup`

What past evidence should the system retrieve about speaker metadata, regional information, or participant forms?

- held-out trigger: `Bmr025` lines 697-699
- source gold spans:
  - `Bmr001` lines 65-67: Past meeting discusses speaker metadata, region, dialect, or forms.
  - `Bmr002` lines 222-224: Past meeting discusses speaker metadata, region, dialect, or forms.

### icsi-span-q004 `decision_rationale`

What earlier decisions or rationale about training data and digit-reading tasks should be remembered for later BMR discussions?

- held-out trigger: `Bmr024` lines 56-58
- source gold spans:
  - `Bmr001` lines 34-36: Past meeting discusses training data, acoustic models, or digit-reading procedures.
  - `Bmr002` lines 194-196: Past meeting discusses training data, acoustic models, or digit-reading procedures.

### icsi-span-q005 `next_meeting_carryover`

What context about recording setup and data-quality issues should be carried into later BMR meetings?

- held-out trigger: `Bmr024` lines 375-377
- source gold spans:
  - `Bmr001` lines 140-142: Past meeting discusses recording setup, data quality, equipment, or constraints.
  - `Bmr002` lines 1-3: Past meeting discusses recording setup, data quality, equipment, or constraints.
