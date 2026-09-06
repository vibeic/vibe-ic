# Consume measured RTL review producer contracts

`rtl_hygiene_lint` and `reset_discipline_check` emit ARRAYS of findings (`[]`
for a clean file). `rtl_precheck_gate` emits an object whose `auditors` value is
an ARRAY of execution results. The review aggregator consumes those actual
contracts. This document records the two decisions that consuming them forced,
because both of them turn on the same question: what is a consumer allowed to
CONCLUDE from evidence it did not fully get?

## 1. Refuse, or report? Two states, and the line between them

`v1.17.43` closed #2036 by making an unreadable producer RAISE, so the CLI exits
3 and writes no report. PR #2039 proposed the opposite for the same inputs: a
named ERROR record inside an emitted report. Both refuse to call an unreadable
producer clean; they disagree about whether an artefact should exist afterwards.

**RULED 2026-09-06: the landed contract wins.** Not on the issue's text — #2036
says "Do not translate the crash into an empty finding set or PASS" and
"Invalid/missing JSON and failed producer execution must remain distinct from a
legitimate clean empty array", which mandates DISTINCTNESS and names no
mechanism, so both designs satisfy it. It was ruled on precedent: v1.17.43 is
landed and was falsified in both directions, and a rebase conforms to it rather
than reversing three landed assertions. That cost was measured before the
ruling, not estimated — reversing them reddens exactly
`TestUnreadableIsNotEmpty::test_unknown_shape_refuses`,
`::test_non_object_records_refuse` and `::test_reset_and_precheck_refuse_too`.
PR #2039's twelve contradicting assertions are retired with a collision table in
`programs/tests/test_rtl_review_hygiene_json.py`'s module docstring; every input
they carried still runs, under the landed expectation.

The line drawn here keeps both, split by what is actually on disk:

* **NO EVIDENCE** — the JSON file is absent, is unparseable, the producer's exit
  code says it reached no verdict, or the payload is not this producer's report
  at all. **REFUSE:** raise, exit 3, write nothing. A report that exists is a
  report someone will quote, and a score computed from nothing is a measured
  number over an unmeasured thing.
* **EVIDENCE PRESENT BUT PARTLY UNTRUSTWORTHY** — a record inside a readable
  array that is not a usable finding (`{}`, `{"severity": "surprise"}`, a record
  with no severity), or an execution list that recorded nothing at all
  (`"auditors": []`). **REPORT:** a named ERROR record — `hygiene_report_invalid`
  / `reset_report_invalid` / `precheck_report_invalid` — inside the emitted
  report, so the real evidence beside it survives and the review can never come
  out clean.

Before this, a record that was a dict but not a finding was accepted with SILENT
DEFAULTS (`severity` → `INFO`, `rule` → `unknown`, `file` → `""`, `line` → `0`),
so a producer emitting junk contributed harmless informational noise; and
`"auditors": []` — nothing ran — scored 10/10 PASS. Those are the same disease as
#2036, one layer in.

## 2. Ruling F2036-H — a skipped auditor is not a finding

`review_rtl_dir` invokes `rtl_precheck_gate` with no `--l12-json`, so
`l12_sequence_implementation_check` always skips. While a skipped auditor was
emitted as an INFO finding, that INFO was counted in the score, so
`compute_score` could never return 10 through this program: a perfectly clean
flip-flop scored 9 and the rubric's documented `10 | 0 errors, 0 warns, 0 infos`
row was unreachable.

**Ruled: a skipped auditor is a fact about the INVOCATION, not a finding about
the RTL, and it does not belong in the score's info count.** PASS, FAIL and
NOT_MEASURED are three states; folding the third into an informational finding
about the code is the two-state collapse this repo refuses everywhere.

The house principle — *a check that did not run is reported, never counted as a
pass* — is kept by the conditions attached to that ruling:

* the report carries `auditors_not_run` (auditor name + why), populated from
  exactly the records the score no longer counts;
* the **Score** and **Verdict** lines print it beside the number, so a 10 reads
  as `10/10 (production-ready) — 1 auditor not run: l12_sequence_implementation_check
  — no --l12-json supplied`, never as a bare 10. A number that can be quoted
  without its coverage is #2036 one level up;
* the record itself stays listed, marked as absence rather than as a finding, in
  its own **Not measured** section;
* `--strict` **DOWNGRADES** (exit 1) rather than **REFUSES** (exit 3) while
  `auditors_not_run` is non-empty. Exit 3 asserts "no verdict was reached and no
  report exists", which is false here: a real review ran over the auditors that
  did run and refusing would destroy that evidence. Exit 1 asserts "I reviewed
  this and I will not certify it as PASS", which is exactly what an unrun check
  makes true. Both artefacts are still written.

**Known consequence, stated rather than softened:** because `review_rtl_dir`
never supplies `--l12-json`, `--strict` cannot exit 0 through this program today.
That is the rule correctly reporting that this driver never supplies L12; the
remedy is for the driver to pass an L12 JSON when one exists, not to weaken the
rule.

## 2b. A skipped auditor's `rule_id` is the auditor NAME

Ruled 2026-09-06, against PR #2039's `<name>_not_measured`. A `rule_id` that
changes with the OUTCOME breaks matching by rule across runs and across
reports: a reader diffing two reviews must find the same auditor under the same
key whether it ran or not. NOT_MEASURED is a STATE, and it belongs in the
record's message and in `auditors_not_run` (§2), never in the identifier.

## 3. The legacy auditor mapping was a fiction

PR #2039 also asked that `{"auditors": {name: {"findings": [...]}}}` remain
readable, as a "historical valid envelope". Measured: `rtl_precheck_gate.py`
appears in 4 commits reachable from `--all` and in every one of them the emission
is byte-identical, `"auditors": [r.as_dict() for r in results]` — a list, never a
mapping; `AuditorResult` has never carried a `findings` field; and the only other
reader of the key in this tree iterates it as a list. No shipped program has ever
written that envelope.

The requirement is **retired**, not silently dropped: its test keeps its node ID
and now pins the measured contract instead — such an envelope is named as
untrustworthy evidence (`precheck_report_invalid`) and can never be read as a
clean review. Implementing the nested form would also have made the dict envelope
ambiguous, since the consumer already accepts `{name: AuditorResult-fields}`.

## What is unchanged

Valid findings retain their rule, severity, file, line and message. Empty
hygiene/reset arrays remain valid clean results. A failed auditor remains an
ERROR. The score formula is untouched. The report is ADVISORY by default and
`--strict` is the blocking mode. No benchmark routing, answer lookup or score
adjustment is involved, and this aggregate does not substitute for flow
compliance or independent semantic review.
