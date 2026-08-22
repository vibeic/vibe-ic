# What goes to `next/` when the freeze lifts

Assembled during the freeze so no time is lost when it does. NOTHING here is in
the frozen branch, and nothing here is a reason to reopen it. Ordered by
(evidence already gathered) x (cost to do). ITEMS 1 AND 3 ARE DONE, on
`next/padring-spacing-provenance`, based on the frozen tip 725f9352f -- not on
pre-batch main, because `next/` rides the batch AFTER this one and the code
those commits touch exists only in the batch. Basing it on main was my first
attempt and the test failed with AttributeError, which is what that phrase
means in practice.

## 1. TAKEN — `next/padring-spacing-provenance`, commit 5ffaab5f6

This step REFUSES an odd remainder at step 7 of upstream's spacing algorithm
where `pad_cfg.tcl` halves and rounds to 3 decimals. The refusal is correct for
integer DEF units -- an odd remainder cannot be halved into two EQUAL gaps, and
upstream would carry a half-DBU a DEF cannot express -- but it is STRICTER than
the tool this step models and is NOT DOCUMENTED AS DELIBERATE. A future reader
comparing the two sees a bug and "fixes" it back into a rounding error.

Evidence: `spacing_transcription_compared.txt` -- all eight steps compared, seven
identical, this one named. Cost: one comment. No behaviour change, no test.

## 2. `next/rc2-clause-path-census` — RULED SHAPE, denominator missing

`flow_compliance_check.py:3134` credits rc=2 as VACUOUS_PASS across 182 gate
clauses invoking 140 distinct programs. `:7220` -- 10 gates -- already separates
"no input to check" from "you called me wrongly", per #492, whose own finding is
that conflating them let 39 gates go permanently silent.

DO NOT change the mapping first. The load-bearing unknown is how many of the 182
return rc=2 in a REAL run, and no such population exists in this record -- only a
constructed project where 1 of 2 gates did. Emit a CENSUS instead: per run, how
many clauses returned rc=2 and which meaning each was, wired ADVISORY.

This needs no new ruling; the standing authority already decided the shape --
the wide-population version becomes a census that records debt and is never
wired as blocking. Evidence: `rc2_clause_path_decision.md`.

## 3. TAKEN — same branch, commit 561d78257

Three defects this session were orientations this step COMPUTED where OpenROAD
PRODUCES them, and they survived every check because a mirror and a rotation
share a bounding box. The fix pins the correct values as constants, which is
right, but a constant can drift from the tool exactly as the old computation
did. The stronger form runs the probe and compares. Cost: needs OpenROAD in the
test environment, which the current suite does not assume -- so it is a real
design question, not a small commit. Evidence: `rotation_probe/`,
`orient_AB_*`.

## Also on that branch: the acceptance gates, run and answered

Commit 5c75c297c. The gates this repo holds changes to had never been run
against `next/` -- only the new test had been graded. All four pass (rc=0):
source_chip_agnostic_check 1544 files, silent_decline_audit 1232,
prose_polarity_consulted_check, gate_zero_denominator_refuses_check 565 gates.
The doctrine's own compliance gate: 2 passed, 1 skipped.

ONE ADVISORY FIRED AND IS ANSWERED IN THE MODULE, not left for a reviewer:
`real_artefact_test_backing_check` reports 0 of 91 tests driven by a CHECKED-IN
artefact. Correct. This module's strongest tests are driven by neither a fixture
nor a checked-in artefact -- they query the installed PDK and the ACTUAL
OPENROAD BINARY, for which the check has no category. Its worry does not apply:
"a suite that cannot distinguish the change from its own absence" is about
fixtures authored alongside the code, which cannot disagree with it. A tool can,
and did. The mutation run the doctrine asks for is recorded beside it.

VERIFIED AGAINST THE POST-BATCH WORLD after every change to the branch: main +
the frozen tip + `next/` merges with 0 conflicts and 107 passed.

## 4-6. Flow-owner calls, unchanged, each with its disconfirming check run

  * extend #564's zero-denominator probe -- a SCOPE decision, not a constraint;
    nothing stops it, I declined it as out of scope for this brief.
  * wire L-documents into the pad assignment -- would CONTRADICT a written
    decision (`flow/phase1_phase2_phase3.yaml` step 15.5ic: slot, then
    declaration, "derives nothing"). A design change, not a precedence ruling.
  * harden premise-checking gates against constructed inputs -- questions a
    premise the flow owner wrote deliberately at step 36.

## NOT on this list, deliberately

The plugin version (the lander assigns it), anything touching `main`, and any
change to the frozen branch. A batch that keeps absorbing one more improvement
never lands.
