# Source-bound spec clarification capture

## Summary

Based on main **1.18.43**, commit
`854d302959d86d6faa9721bea784a989f5e23a17`. Version-less contributor PR;
Gatekeeper owns any later rebase, revalidation, version assignment, and landing.

The captured gap is a missing **workflow state**, not a demonstrated simulator
defect or a newly repaired RTL design. An AI can identify an obligation whose
expected behavior is not defined well enough to derive a failing test. Previously
it could only choose PASS or FAIL: an unproven FAIL becomes REJECTED and goes
back to AI review, with no machine-readable request for the missing definition.

Bucket A implementation is in the plugin programs, not a skill-only instruction.
`capture.json` names the automatic consumption points. The generic core is
chip-agnostic: production changes contain no design/PDK/vendor literals, no
benchmark-ID dispatch, no answer templates, and no inferred standards predicate.
Tests use invented specs. The separate corpus evidence uses public inputs only.

## Contract and automatic consumption

`spec_review_lint` automatically reads the optional project-local
`reports/spec_clarification_review.json` during its existing D1 invocation.
`--clarification-review PATH` selects an explicit declaration. JSON output adds
`spec_clarification` without changing structural lint findings or verdicts for a
valid declaration. Absent means `NOT_REVIEWED`, never semantic PASS. Malformed,
wrong-source or stale declarations produce a named ERROR, not silent fallback.

```json
{
  "schema": "vibeic.spec_clarification.v1",
  "source_sha256": ["<hash of every distinct supplied raw source text>"],
  "requests": [{
    "source_sha256": "<the quoted source hash>",
    "excerpt": "<verbatim obligation from that source>",
    "missing_information": "<concrete missing definition, at least 16 characters>",
    "question": "<specific question for the spec owner, at least 16 characters>"
  }]
}
```

Hashes cover the whole supplied corpus, including duplicate-content deduplication;
an added or changed chapter invalidates an old declaration. Excerpts must belong
to their bound source (whitespace normalization is allowed only for quote matching).
The program validates the declaration's structure and bindings. It does **not**
prove that the AI's semantic interpretation is correct or automatically discover
all ambiguities from prose.

The ordinary D1 gate remains **ADVISORY**. This PR does not claim a new general
RTL-authoring stop or promote existing structural warnings to BLOCKING.

The benchmark adapter emits the same conditional envelope in the normal review
task. A fresh AI review can select `NEEDS_CLARIFICATION` and include
`spec_clarification`. After normal prompt/RTL/snapshot, reviewer, blindness,
route and provenance checks, Program returns `SPEC_CLARIFICATION_REQUIRED` and
resume writes `needs_spec_clarification.jsonl` with the exact questions. This
case remains in the denominator, pending the spec owner rather than another
identical AI-review/RTL-repair attempt. Earlier repair handoffs retain their
evidence but are explicitly inactive while clarification is pending.

The existing acceptance/scoring boundary remains **BLOCKING**: no acceptance,
no repair authorization, no response publication, no scoring. Existing tests are
retained as NOT_RUN during clarification; none is superseded or waived. A
clarification object cannot accompany PASS/FAIL. A changed prompt requires a new
canonical run and fresh review, never mutation of frozen benchmark evidence. If
the AI withdraws an erroneous question about an unchanged complete prompt, its
ordinary replacement review must still satisfy all existing executable proof,
coverage and inherited-test requirements. There is no resolved/PASS shortcut.

## Verification

Pre-fix negative controls: **4 FAIL**; post-fix: those same **4 PASS**.
`control_substance_check --junit control-before.xml` measured four observed-value
failures, zero presence-only/import/collection failures. The controls use the
existing CLI and resume entry points, not unsupported flags or missing APIs.

The selected six existing test modules give 171 baseline PASS; the candidate
gives 211 PASS including 40 new tests. `verification.json` lists exact test-ID
name sets, source hashes and JUnit hashes: missing baseline IDs = 0, new failure
set = empty. No broad regression, baseline waiver, skip or assertion removal.

Prove-by-run: `test_real_resume_waits_on_spec_without_repair_acceptance_or_score`
runs actual `cmd_resume`, observes rc=2, one question task, zero repair tasks,
zero accepted responses, unchanged frozen bytes, and the actual scoring guard
raising acceptance BLOCKED. Repeated resume preserves the same worklist.

Corpus sweep: **69 public-input corpora, 0 false positives introduced**; exact structural
findings, verdicts and exit codes unchanged. `corpus-sweep.json` carries every
case's source hashes and before/after result. This measures compatibility of the
new diagnostic channel, not proof that the old advisory lint has zero semantic
false positives. No review was present in that sweep, so all new states are
honestly NOT_REVIEWED.

A separate source-bound diagnostic against the remaining public decoder prompt
produced SPEC_CLARIFICATION_REQUIRED with a concrete predicate/error-policy
question. It is not a replacement independent benchmark review. All 139 input
and acceptance-ledger hashes remained unchanged. No oracle, golden RTL, hidden
testbench, new benchmark solve, or scorer was used.

Engineering acceptance stays **68/69**; official score remains NOT_RUN. This
capture does not supply the missing normative predicate, declare a benchmark
defect, or claim the remaining case passes. There is no reproduced EDA tool
defect to fix in this capture; simulator behavior cannot define a missing spec.

### Reproduction

Run these six existing modules on the pinned base and candidate:

```text
programs/tests/test_spec_review_lint.py
programs/tests/test_spec_review_lint_language_and_applicability.py
programs/tests/test_spec_review_lint_blockquote_is_not_prose.py
programs/tests/test_spec_review_lint_corpus_scope.py
programs/tests/test_benchmark_program_first_ai_review.py
programs/tests/test_ai_review_correction.py
```

Add both new `test_spec_clarification_review.py` and
`test_benchmark_spec_clarification.py` for the candidate. For the pre-fix control,
put the unchanged new test files on the pinned base and select
`test_existing_cli_automatically_exposes_clarification_without_changing_lint`
(two parameters), `test_existing_validator_distinguishes_question_from_rejected_review`
and `test_real_resume_waits_on_spec_without_repair_acceptance_or_score`.
Use `pytest --junitxml=...`; compare full node-ID sets, not just counts.

Corpus invocation is the existing D1 command, once per arm/project:
`spec_review_lint.py --strict input/docs/*.md input/docs/*.rst input/*.md --json REPORT`.
Use the public-input source hashes in `corpus-sweep.json` to bind the input set;
write reports outside the frozen run. No source corpus is bundled into this PR.

## Next

Proceed to Gatekeeper review and landing. On a future run, Program consumes the
clarification declaration automatically; AI supplies semantic judgment. Obtain
the missing source definition before attempting a new answer or claiming closure.
