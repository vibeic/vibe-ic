# Immutable AI review correction on unchanged RTL

`benchmark_dispatch.py --resume --review-correction REQUEST.json` adds an
explicit correction round for an **unaccepted** current review. It is shared
by every adapter using the normal dispatcher. It does not author RTL, choose a
route, invoke a scorer, change Program gates, or accept a candidate.

## Why a new round

An AI test may assert a value inconsistent with the public prompt. Replacing
that test at its existing path would destroy the evidence. Changing correct
RTL merely to get a new review key would manufacture a repair.

The operation preserves the exact current task, review and challenge, keeps
the candidate and prompt unchanged, issues fresh review/test paths, and moves
the old current challenge into the ordinary inherited challenge list. The
reviewer's correction request is an explanation, **not a repair permit and not
a test supersession**. The subsequent independent review must still use the
existing prompt-grounded `challenge_supersessions` mechanism, pass its different
replacement test, and satisfy every active structural review obligation.

## Request and invocation

Read the current task from `needs_ai_review.jsonl`. Supply a JSON object with
the following fields, using actual values rather than the placeholders:

```json
{
  "schema": "vibeic.benchmark.ai_review_correction.v1",
  "id": "<current task id>",
  "task_sha256": "<canonical task digest>",
  "prompt_sha256": "<task.prompt_sha256>",
  "rtl_sha256": "<task.rtl_sha256>",
  "review_sha256": "<SHA256 of exact current review file bytes>",
  "challenge_sha256": "<current review.verification_test.sha256>",
  "author": {"kind": "AI", "model": "<actual reviewing model>"},
  "blind": {"oracle_accessed": false},
  "rationale": "<at least 80 characters explaining the current test defect>",
  "prompt_evidence": [{
    "excerpt": "<exact public prompt excerpt, at least 8 characters>",
    "supports": "<claim supported by that excerpt, at least 12 characters>"
  }]
}
```

The canonical task digest is SHA256 of UTF-8
`json.dumps(task, ensure_ascii=False, sort_keys=True)`, without a trailing
newline. Prompt and RTL hashes retain the existing task contract. Test hashes
retain the existing challenge text-hash contract; archive copies preserve raw
UTF-8 file bytes, including their line endings.

```bash
python3 programs/benchmark_dispatch.py <bench> --resume \
  --dataset <dataset> --run <run> --jobs 1 --heavy-jobs 1 --worker-threads 1 \
  --review-correction <request.json>
```

The correction operation reads task-bound local public/evidence files only,
not dataset contents. The enclosing ordinary resume retains its existing
dataset argument and product route. `--review-correction` is invalid with
solve, score, show or list. After the operation, obtain the new task from the
worklist, author its new independent review/test, then use ordinary `--resume`.
Expected correction-only outcome is pending (exit 2), not a successful score.

## State, refusal and restart contract

This is **BLOCKING**: invalid requests stop before ordinary resume and emit
`REVIEW_CORRECTION_REFUSED`. A second coordinator is refused by the existing
run-root lock. Rejected conditions include missing/malformed evidence,
unattributed/non-blind requests, absent prompt quotes, source/hash drift,
changed working RTL, symlink paths, evidence outside the run, occupied new
paths, or an already accepted/published candidate. A request is not a way to
retract a published score.

Immutable records live under
`review_corrections/<safe-id>/<request-file-sha256>/`: prior task, exact prior
review/test, exact request, and a transition containing both task states and
source hashes. Original evidence also stays at its original paths. Archive
creation finishes before one atomic replacement of the authoritative review
worklist. All original inputs are rechecked before this commit.

- Before the commit, interruption leaves the old task active. Repeat the
  identical request to reuse identical prepared archives and finish.
- After the commit, interruption leaves a fresh, unreviewed task active.
  Ordinary resume derives the pending ledger and worklists from this task;
  repeat the same request to verify archives and report `ALREADY_APPLIED`.
- The acceptance ledger/repair worklist may still describe the previous
  pending state until ordinary resume finishes. They do not authorize an RTL
  edit: the authoritative task and the normal proof predicate still control
  repair. The correction itself never publishes a response.
- Replay refuses missing/modified completed archives, changed input files or
  an unrelated later task. It never silently creates another correction round
  or overwrites a newly authored test.

The lock coordinates product writers; it is not a security boundary against
an adversary mutating the filesystem concurrently. Hash checks detect drift
observed during preparation. Atomic replacement provides process-interruption
safety, not a new filesystem/power-loss durability guarantee.

## Verification boundary

`programs/tests/test_ai_review_correction.py` exercises the real state
transition and normal acceptance path, including successful explicit inherited
supersession, no-supersession refusal, failing replacement, incomplete coverage,
idempotence, interrupted commits, drift, missing archives and symlinks. A test
reads an existing public datasheet-shape fixture through `_hostpaths` to verify
the transaction's prompt-evidence handling; it does not pretend its neutral RTL
implements that entire datasheet.

The pre-fix control runs the same real old resume entry when the correction
argument does not exist. Its observed outcome remains `REPAIR_REQUIRED`, not
the required fresh `PENDING` review. Missing APIs/imports are not counted as
proof of the behavioral fix. Adjacent inherited-supersession and coverage tests
remain required. These are focused flow tests, not an official benchmark score
or a claim of full-flow compliance.
