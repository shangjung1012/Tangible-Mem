# Short-Term Active-State Applied Manual Review

Run: `short_term_active_state_applied_20260511_050552`

Baseline: `short_term_ablation_20260511_020452`

## Verdict

The applied short-term JSON migration is acceptable. It writes the new
active-state fields into `short_term/short_term_memory.json` and the existing
per-meeting short-term snapshots without changing raw L1 evidence.

This does not turn short-term into a historical evidence retriever. That is
intentional. Short-term now behaves more like an active working-state layer,
while long-term remains responsible for cross-meeting evolution and detailed
evidence grounding.

## Quantitative Check

- Old broad unit-source recall: `0.808`
- New active-source recall: `0.3899`
- New visible-gold recall in prompt: `0.3408`
- Recent short-term query visible recall: `0.8056`
- Average selected active source ids: `51.12`
- Old selected legacy source ids: `269.5`
- Average context chars: `3310.75`

The old `0.808` recall counted all historical L1 ids inside oversized S-units.
The new metric is stricter because prompt-visible active sources are bounded to
recent evidence. The important improvement is that visible prompt evidence rose
from the earlier manual estimate of about `0.146` to `0.3408`, and recent
short-term questions reached `0.8056`.

## Manual Case Notes

### VM-E01: transcript segmentation pipeline

Good. The top S-unit still has broad lineage, but active source preview exposes
the current 0506 evidence:

- `L1-0506-001`
- `L1-0506-002`
- `L1-0506-003`

The remaining gold item is still active but not visible in the final preview
slice. This is acceptable because the answer has enough active evidence, and
long-term can supply full evidence when needed.

### VM-E02: segmentation open issues

Strong. All expected current 0506 evidence appears in the prompt:

- `L1-0506-005`
- `L1-0506-007`
- `L1-0506-008`
- `L1-0506-009`
- `L1-0506-010`

This confirms the previous hidden-source problem is fixed for the most
important recent short-term case.

### VM-E05: importance / activation / recency

Good enough. `S021` is specific and ranked first; it exposes direct evidence
for user-tunable importance. The LTM architecture unit contributes the topic
structure evidence. Full design history still belongs to long-term.

### VM-E08, VM-E10, VM-E12, VM-E14: hybrid / long-term cases

These are not short-term-only questions. The active-state filter intentionally
does not surface all older 0318/0408/0422 evidence. The correct behavior is to
let short-term provide recent framing while long-term L1/L2/L3 supplies the
historical evolution.

### VM-E13: speaker diarization

Short-term does not recover the old 0307 evidence, which is correct. This is an
older preprocessing assumption rather than a current active-state item.

## Remaining Risks

- Existing S-unit summaries are still broad and partly English because this was
  a schema/field migration, not a full API rebuild.
- `S001`, `S004`, and `S006` still have broad full lineage. The prompt now shows
  bounded active source previews and emits diagnostics, but a future short-term
  rebuild should split broad active-state units more cleanly.
- A full Gemini rebuild was intentionally not run in this pass to avoid spending
  hundreds of API calls before the active-source contract was validated.

## Decision

Keep this migration and retrieval behavior. The next improvement should be a
controlled rebuild/split of broad active-state S-units, preferably on the latest
three meetings first, with the same visible-evidence validation gate.
