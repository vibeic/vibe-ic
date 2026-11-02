# Step 4 can measure a reference model filled after it asked for one

## Summary

**STATUS**: IMPLEMENTED_PENDING_INDEPENDENT_REVIEW. A route whose evidence window includes Step 4 could reach a state it could never leave. Program cannot derive the reference, so the first re-gate reports `sim` FAIL on the unfilled hook and asks for a model and a re-run. The dispatcher then has no way to re-run: unchanged RTL is a no-op, changed RTL without a proven failure is `UNPROVEN_AI_EDIT_REJECTED`, and `--program-regate` accepts only `AI_REPAIR`. A semantic PASS does not discharge the failure, so the run stays PENDING and can never be scored.

Three small changes close it, reusing what exists:

- The producer's gate report now names the model it measured (`reference_model_sha256`).
- Ordinary `--resume` plans the existing same-bytes `regate` when a required `sim` failed and a different accepted model is now present. Nothing else re-enters, so a repeated resume cannot loop and a real mismatch stays a failure.
- The AI backup task names the model path before the first re-gate, as a conditional advisory, so a review is not spent on a candidate Step 4 could not measure. The `PROGRAM_GATE_INELIGIBLE` row names the model when that is what Step 4 is waiting on, instead of telling the author to repair correct RTL.

There is no new record, journal, gate or admission rule. A model does not grant acceptance: the ordinary native result and a fresh independent review still decide.

## Verification

Neutral end-to-end control through the public CLI and the real runner, on an invented four-bit parity repair, at the same parent on both arms:

| Step | Base | Candidate |
|---|---|---|
| Re-gate, hook unfilled | `INELIGIBLE: sim` | `INELIGIBLE: sim` |
| Correct model filled, `--resume` | `INELIGIBLE: sim`, 0 re-gates, same review key | `ELIGIBLE (3 in-scope PASS)`, 1 re-gate, fresh review key |
| Repeat `--resume` | unchanged | no further re-gate |

Second candidate sequence, wrong-behavior control:

| Step | Candidate |
|---|---|
| Wrong model filled, `--resume` | 1 re-gate, `INELIGIBLE: sim` |
| Repeat `--resume` | no further re-gate |
| Model corrected, `--resume` | 2 re-gates, `ELIGIBLE` |
| Repeat `--resume` | no further re-gate |

Focused tests: 26 new, all passing. Matched panel of the 134 test files that name the dispatcher or the producer, same parent, separate temp roots: `NEW_FAILED=[]`, no missing IDs. That panel is not green on either arm: 722 IDs fail on both, largely environment refusals in a linked worktree such as `CANONICAL_ISSUANCE_INVALID`. Those IDs did not measure this change. 11 IDs failed only on the base arm with `LIVE_PLUGIN_PATH_AFTER_RETENTION`; they are unrelated to this change and are not claimed as fixed.

These are component controls. They do not establish benchmark acceptance or a score.

## Next

Proceed to independent review.
