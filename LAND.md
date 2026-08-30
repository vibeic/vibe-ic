# LAND.md — reland/rc1-triage-not-checked-tier

## REF
`reland/rc1-triage-not-checked-tier`

## BASE
`70afd8a69` — main at v1.13.87, freshly fetched and measured 2026-08-31.

REBASED AFTER THE LANDED-SO-FAR BROADCAST. This branch was previously based on `4015aba45`,
the head of PR #1929; that work LANDED as `d155935a7` (v1.13.85), so the base was superseded.
The branch was rebuilt from `70afd8a69` replaying ONLY the fix commit — the register commit
was dropped as already-landed, and the cherry-pick was clean.

BOTH DEFECTS WERE RE-MEASURED ON `70afd8a69` AND ARE STILL LIVE. This is not a re-submission
of landed work:

    D1  gate_evidence_completeness_check on /home/reyerchu/_c_spm_run at 70afd8a69
        "no FINAL_REPORT or flow compliance JSON found" / "FAIL: nothing to audit"   rc 1
    D2  the dfm_screen_check advisory_reason on main still reads "it REFUSES TODAY on real
        input ... Promote to blocking once this run is clean" — v1.13.85 landed the wrong
        reason verbatim, and main's docstring census still reads NOT-YET-CLEAN 62 /
        CENSUS 2 / (15 rc 1, 30 rc 0, 17 rc 2).

The register itself on main is healthy — 84 clauses in 78 programs, 84 STATED, 0 recorded as
debt, rc 0 — so nothing about it needs redoing. Only these two entries are wrong.

## DEFECT

Two defects, both found by triaging the rc-1 clauses the advisory slot swallows. Neither is a
design finding; both are instruments that mis-state what they measured.

### D1 — `gate_evidence_completeness_check` answers a question it never asked, with the word FAIL
On a real completed run tree the program prints

    gate_evidence_completeness_check: no FINAL_REPORT or flow compliance JSON found
    FAIL: nothing to audit                                                        rc 1

It has read nothing, so it has no design to return a verdict about. Its OWN docstring defines
`1 = gaps found, 2 = I/O error`, and the two branches on either side of this one already route
to 2 (`not a directory`; `cannot parse JSON`). The absent-report branch was the only one of the
three that reported an unasked question as a failure.

This repo already names the class. `gate_zero_denominator_refuses_check` exists because gates
were "returning a verdict about a design [they] had not read", and its three worked examples
include `fpga_qsf_lint "ERROR: QSF file not found" rc 1`. That program is deliberately only the
PROBE — "each fix is then its own measured change". This is that change, for this one gate.

Consequence in the flow: the advisory slot rendered it `__ADVISORY_HINT__FINDING`, so the
register carried a finding against a design nobody had looked at.

### D2 — the `advisory_reason` for `dfm_screen_check` contradicts its own quoted evidence
The reason #1929 introduces for that clause reads:

    "it REFUSES TODAY on real input; the advisory slot is currently swallowing a live
     finding. Promote to blocking once this run is clean. It reported: dfm_screen_check:
     PASS_WITH_ADVISORIES ..."

`PASS_WITH_ADVISORIES` is quoted two lines after "it REFUSES". `dfm_screen_check` is the ONLY
one of the 18 rc-1 clauses that declares rc 1 as a non-failure tier — `0 PASS / 1
PASS_WITH_ADVISORIES (the screen ran and RAISED a finding) / 2 vacuous SKIP` — and the same
docstring states the flow MUST wire it in the advisory slot. Acting on that reason would fail
every run that raises any advisory at all, which is the opposite of what the gate's author
documented. A reason that misinforms is worse than the silence it replaced; that is the
register's own stated standard, and this entry failed it.

## TRIAGE — the three with the largest signal, kind named first

Picked for signal: the loudest number in the register, the only governance allegation, and
the one whose own output says it audited nothing.

| clause | kind | verdict |
|---|---|---|
| `dfm_screen_check` — 4129/4129 signal-net via uses | **(b)** | The check measures our own tri-state convention and is red because we obeyed it. rc 1 is its declared PASS_WITH_ADVISORIES tier. 4129/4129 is UNMEASURED, not violated: the vias are "declared neither in the DEF VIAS section nor in any locatable tech LEF", and the screen deliberately does not infer a cut count from an absent declaration. Nothing to fix in the check or the policy — but the register entry describing it was wrong, and that is D2. |
| `waiver_growth_check` — 4 waivers past a zero tolerance | **(c)** | `baseline: ABSENT — no file at .vibe-ic-state/waivers_baseline.json; compared against an empty document (0 root waivers)`. Every current waiver counts as new because there is no reference. This is growth being unmeasurable, not a control being bypassed. NOT FIXED: freezing a baseline is exactly the "add a file to satisfy it" that is forbidden, and would manufacture a green over an unmeasured question. Whether an absent baseline should be rc 2 is its owner's call — its message is a deliberate call to action and rc 2 would hide it. |
| `gate_evidence_completeness_check` — "FAIL: nothing to audit" | **(c)**, with a real **(a)** in the instrument | The design finding is (c): the inputs do not exist. The instrument defect is real and is D1. |

Fixed: D1 and D2. Not fixed: the two (b)/(c) findings above. Nothing was flipped to blocking.

## EVIDENCE

Measured on `/home/reyerchu/_c_spm_run` (spm x sky130, phase1+phase2+phase3 present):

    BEFORE   gate_evidence_completeness_check .
             "gate_evidence_completeness_check: no FINAL_REPORT or flow compliance JSON found"
             "FAIL: nothing to audit"                                            rc 1

    AFTER    "VACUOUS_PASS: gate_evidence_completeness_check examined nothing (reason: no
              FINAL_REPORT.md or flow-compliance JSON in this run) — this is NOT a pass over
              the design"
             "[VACUOUS] gate_evidence_completeness_check — examined nothing (...); this is
              NOT a pass over the design"                                        rc 2

`VACUOUS_PASS:` is the sentinel `flow_compliance_check._stdout_signals_vacuous` matches, so
the advisory slot now records `n/a (input not present)` in place of a FINDING.

Systemic check behind D2 (`_triage17/rc1_semantics.txt`): all 18 rc-1 gates were read for a
declared meaning of rc 1 in their own docstring. Exactly one — `dfm_screen_check` — declares
it as a non-failure tier. The other 17 use rc 1 in the ordinary "found findings" sense, so D2
is a single wrong entry and not a class of them.

Register after D2: `84 of 84 STATED`, `0 recorded as debt`, rc 0. Class counts in the gate's
docstring census corrected with it — NOT-YET-CLEAN 62 -> 61, CENSUS 2 -> 3, rc-1 notch
15 -> 14 — and the lesson recorded there so the next author does not read rc 1 as one fact.

## ARMS

Five test files, same host, run back to back, both on `70afd8a69`:

```
ARM A  fix in                     8 failed, 249 passed, 1 skipped, 6 xfailed
ARM C  plain main 70afd8a69       8 failed, 247 passed, 1 skipped, 6 xfailed
```

Failure SETS diffed in BOTH directions: A-only is empty and C-only is empty. The fix adds no
failure and removes none. The +2 in ARM A is the two tests this change adds.

An earlier pair on the superseded base (fix in vs fixes reverted) gave the same shape —
8 failed / 249 passed against 8 failed / 247 passed.

NEGATIVE CONTROL — a test that cannot fail against the pre-fix code proves nothing:

```
new tests vs PRE-FIX program      1 failed, 3 passed
    test_absent_report_is_not_checked_not_a_failure FAILED, as it must
new tests vs fixed program        4 passed
```

The other two new tests are green in BOTH directions on purpose. They pin the two branches
that must NOT move — a report that was READ with zero PASS claims stays rc 0 ("an empty
artefact is not a missing one"), and a PASS claimed with no evidence STILL returns rc 1. A
change that silenced this gate rather than re-tiering one branch would show up there and
nowhere else.

## PREEXISTING

Present in BOTH arms and on untouched main; not this change's, not touched here:

```
programs/tests/test_matrix_d2_falsifiable.py::test_d2_gate_has_a_reachable_fail[step37.5ip]
programs/tests/test_matrix_d2_falsifiable.py::test_d2_gate_has_a_reachable_fail[step37.5ic]
programs/tests/test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step2]
programs/tests/test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step14]
programs/tests/test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step15]
programs/tests/test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step37]
programs/tests/test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step37.5ip]
programs/tests/test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step39]
```

The five non-`step37.5` d7 ids arrived with v1.13.78 itself and were reproduced on an
untouched checkout of `93235bdf3`.

## BODY

NOT CHECKED is not FAIL, and rc 1 is not the same fact in every gate

Two instruments were mis-stating what they measured. Both were found by triaging the rc-1
clauses the advisory slot swallows; neither is a design finding.

`gate_evidence_completeness_check` printed "FAIL: nothing to audit" and returned 1 when
neither a FINAL_REPORT.md nor a flow-compliance JSON existed -- a verdict about a design it
had not read one byte of, which the flow's advisory slot then recorded as a FINDING. Its own
docstring defines rc 1 as "gaps found" and already routes the two neighbouring I/O conditions
(not a directory; cannot parse JSON) to rc 2; the absent-report branch was the only one of
the three answering an unasked question. `gate_zero_denominator_refuses_check` already names
this class and lists `fpga_qsf_lint "ERROR: QSF file not found" rc 1` among its worked
examples, and says each fix is its own measured change. This is that change, for one gate.
It now emits the `VACUOUS_PASS:` sentinel and rc 2, so the slot records `n/a (input not
present)`. Measured on a real spm run: rc 1 -> rc 2.

The rc-0 branch is deliberately untouched. A report that was READ and claims no PASS gate is
a real result over a real artefact: an empty artefact is not a missing one.

The second fix is to a reason this repo shipped one commit ago. The `advisory_reason` for the
`dfm_screen_check` clause said "it REFUSES TODAY ... Promote to blocking once this run is
clean" while quoting `PASS_WITH_ADVISORIES` as its own evidence two lines later. Measured
over all 18 rc-1 clauses, exactly one declares rc 1 as a non-failure tier -- that one, whose
docstring defines 0 PASS / 1 PASS_WITH_ADVISORIES / 2 vacuous SKIP and states the flow MUST
wire it advisory. Promoting it to blocking would fail every run raising any advisory at all.
The clause is now classed CENSUS with a reason that says what it counts and that its
4129/4129 is UNMEASURED -- the vias are declared in neither the DEF VIAS section nor any
locatable tech LEF -- rather than violated. Class counts in the docstring census follow
(NOT-YET-CLEAN 62 -> 61, CENSUS 2 -> 3), and the lesson is recorded there.

Two findings triaged and deliberately NOT fixed, named so they are not silently dropped.
`waiver_growth_check` reports 4 waivers added past a zero tolerance; its baseline file is
ABSENT, so it compared against an empty document and every current waiver counts as new.
That is growth being unmeasurable, not a control bypassed, and freezing a baseline to clear
it would manufacture a green over a question nobody asked. `dfm_screen_check`'s own finding
is the check measuring our convention correctly and needs no change.

NOTHING IS FLIPPED TO BLOCKING. That is a separate decision with a separate blast radius.

ARMS: fix in 8 failed / 249 passed; control with both fixes reverted 8 failed / 247 passed --
identical failure set, the +2 being the tests this adds. NEGATIVE CONTROL: the new tests run
against the pre-fix program give 1 failed / 3 passed, the failure being the one that must
fail; against the fixed program 4 passed. The other two new tests are green in both
directions by design -- they pin the branches that must not move, including that a PASS
claimed without evidence STILL returns rc 1, so a fix that merely silenced the gate would be
visible there.

PREEXISTING (both arms, and on untouched main): test_matrix_d2_falsifiable::
test_d2_gate_has_a_reachable_fail[step37.5ip] and [step37.5ic]; and
test_matrix_d7_outputs_list_complete::test_d7_required_outputs_list_is_complete on [step2],
[step14], [step15], [step37], [step37.5ip], [step39]. The five non-step37.5 d7 ids arrived
with v1.13.78 and reproduce on an untouched checkout of it.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.

## PRE-EXISTING, OBSERVED NOT TOUCHED

`flow/phase1_phase2_phase3.yaml:6110` carries a comment written in Chinese, not English. It is
present at BASE `4015aba45` unchanged (23 CJK characters in both), so it is not this change's
and not #1929's. It is named here rather than edited: this branch touches that file for one
`advisory_reason` value, and translating an unrelated line would put a change in the diff that
neither defect accounts for. Everything this branch ADDS is English.
