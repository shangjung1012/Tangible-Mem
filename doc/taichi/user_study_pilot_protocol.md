# Tangible Mem Planned Pilot Protocol

Status: planned pilot. This is not completed user-study evidence.

This protocol is a ready-to-run plan for evaluating whether people can inspect,
diagnose, and correct AI-generated hierarchical memory in Tangible Mem. It should
not be described as completed user-study evidence until participants have been
recruited, sessions have been run, and results have been analyzed.

## Study Goal

The pilot tests whether the Memory Observatory interface helps a reviewer answer
four practical questions about long-term research meeting memory:

1. What source evidence supports this answer?
2. Which L1 memory objects were retrieved first?
3. How did L2 topic context and L3 navigation affect the trace?
4. What sidecar correction should be recorded when the effective memory view is
   wrong, outdated, too broad, or poorly linked?

## Participants

Target participants are graduate students or researchers who are familiar with
reading meeting notes, transcripts, or research project records. The pilot can
start with 3 to 5 internal participants before any broader study.

## Materials

- Tangible Mem / Memory Observatory running on the ICSI demo dataset.
- Retrieval Trace screenshot or live UI.
- Topic Observatory screenshot or live UI.
- Memory Explorer and Correction Review tabs.
- The task packet in `doc/taichi/user_study_task_packet.md`.
- The scoring sheet in `doc/taichi/user_study_scoring_sheet.csv`.

## Procedure

1. Brief participant on the evidence-status boundary:
   - L1 is source-derived evidence.
   - L2 is derived topic state.
   - L3 is navigation context.
   - sidecar correction changes the effective memory view, not raw evidence.
2. Ask the participant to complete the task packet.
3. Ask the participant to think aloud while inspecting retrieval traces.
4. Record task time, confidence, diagnosis accuracy, and correction
   appropriateness.
5. Debrief with questions about confusing labels, missing evidence, and whether
   the sidecar correction workflow felt understandable.

## Measures

- diagnosis_accuracy: whether the participant correctly identifies whether the
  answer is supported by source evidence.
- source_traceability: whether the participant can name the relevant meeting and
  evidence location.
- correction_appropriateness: whether the chosen sidecar correction matches the
  observed problem.
- topic_navigation_usefulness: participant rating for L2/L3 topic context.
- confidence_after_trace: participant confidence after inspecting the trace.
- qualitative_notes: free-form confusion, trust, or interface feedback.

## Claim Boundary

The study can support HCI claims only after it is run. Before that, it supports
a narrower statement: Tangible Mem includes an implemented inspection and
sidecar correction workflow that is ready for pilot evaluation.
