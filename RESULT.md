# RESULT — wiring the PPA stack, and the one blocking clause that could not go red

Branch `jwire/ppa-wiring`, four commits on `land/ppa-tf` (bb90724dc, the
v1.11.19..v1.11.32 stack). Base for every A/B below is `origin/main 867de4289`,
which is the merge-base of the stack.

No plugin version bumped. No hygiene baseline written. Nothing pushed to main.

---

## 0. THE SCOPE CHANGED MID-TASK, AND THIS RECORDS WHAT IT CHANGED TO

The brief named six new reds. The re-measurement that arrived while this was in
flight found that five of them were an xdist artefact — tests that MUTATE the
shipped tree racing tests that READ it under `-n 10` — and that exactly ONE was
real. That matches what was measured here independently:

* item E, both files — **artefacts**. Not reproducible serially.
* item F, `test_issue1130_wiring_population_parity.py` — **artefact**. Run
  serially against this branch, with the wiring in place: **7 passed, 0 failed**
  in 63.94s. It also collects more cases on this arm than on main, because the
  wiring gates now enumerate more programs — the wiring being visible, not
  broken.
* `test_the_generator_cli_can_go_red_and_green` — red on BOTH arms serially.
  Pre-existing on main and owned elsewhere. Untouched here.
* item D, `test_d2_gate_has_a_reachable_fail[step33]` — **real**, and fixed
  below.

Items A, B and C never rested on pytest. Their evidence is the hygiene run, and
all three are real and are done.

---

## 1. ITEM D — the one real finding: a blocking clause no input could redden

`test_matrix_d2_falsifiable.py::test_d2_gate_has_a_reachable_fail[step33]`
is green on `867de4289` and red on the stack:

    step 33: 1 blocking clause(s) reached no content-earned FAIL and are not in
    UNREDDENED:
      'power_total_vs_budget_check . --json reports/phase2/gates/power_budget'
      -> VACUOUS_PASS (fixture POWER_OVER_BUDGET)

### What it actually is

Reproduced by hand against the fixture tree, on the stack:

    $ power_total_vs_budget_check . --json reports/phase2/gates/power_budget.json
    INCOMPLETE: total power was NOT compared against anything — missing
    authority: the total-power record's activity basis is 'UNSTATED'; a power
    figure whose activity model is unknown cannot be judged against a threshold.
    rc=2

The gate did not weaken. It got **stronger**. v1.11.22 (the jppa-power lane)
made a watt figure incomparable until its ACTIVITY BASIS is known, because a
vectorless estimate and a VCD-driven measurement are both "total power" and are
not the same number. `POWER_OVER_BUDGET` predates that rule and states no basis,
so it now yields rc 2 — and rc 2 aggregates as VACUOUS_PASS. The clause stopped
being falsifiable *silently*, while the fixture still looked like it worked.
That is precisely the class of defect the D2 matrix exists to catch, and it
caught it.

### The fixture

One line of FIXTURE, not one line of gate: `POWER_ANALYSIS_MODE: vectorless_sdc`
on the power report — the label 3 of the 17 published power reports carry.

    $ power_total_vs_budget_check . --json reports/phase2/gates/power_budget.json
    [FAIL] power_total_vs_budget_check: read 1 total-power figure(s) from the
    power report family and 1 L19 copy/copies
      Activity basis of the reports read: VECTORLESS=1.
      - POWER_TOTAL_OVER_BUDGET: total power 3.3000e+02 uW
        (reports/phase2/power.rpt, activity basis VECTORLESS) exceeds the
        declared budget 1.0000e+02 uW (L19.power_budget_uw) by 3.3x
    rc=1

A content-earned FAIL: 330 uW against a declared 100 uW, both halves read from
the tree, the finding naming both numbers and their sources.

`vectorless_sdc` and **not** a vector mode, deliberately. `_ppa/power.py` marks a
declared vector basis CONTRADICTED unless the transcript corroborates it (zero
published vector report in this repository does), so a fixture that faked a
corroborating annotation count would be asserting an activity model it never ran.

### What was NOT done, and both were available

* **Not registered in `UNREDDENED`.** That register publishes gaps that exist;
  it is not a place to file one you could close.
* **The gate was not weakened.** A blocking clause no input can turn red is the
  defect, not the test.

### The mutation arm

Delete the mode line from `_f_power_over_budget` and
`test_d2_gate_has_a_reachable_fail[step33]` goes red naming that clause. That is
the arm, and it is the test that found this in the first place — which is why no
second test was added: a redundant pin over the same predicate buys nothing and
adds a surface to drift.

Whole file, this branch: **1 failed, 84 passed, 2 xfailed**.
Whole file, `867de4289`: **1 failed, 84 passed, 2 xfailed**.
The one failure is `[step1.6x]` on both arms — pre-existing, untouched.

---

## 2. ITEM A — the six unwired gates, decided per program with the rc measured first

`checker_execution_wiring_audit` and `gate_is_wired_check` both named seven
programs on the stack; six are the stack's own and the seventh is base debt
(§5). The lanes could not wire them: `tools/ci/` and `flow/` are single-writer
surfaces they were forbidden to touch.

| program | venue | wrapper | rc measured BEFORE the wrapper was chosen |
|---|---|---|---|
| `closed_loop_executable_coverage_check` | `tools/ci/repo_hygiene_gates.sh` | `run` | **rc 0** — "22 declared closed_loop edge(s) over 69 step(s); DECLARED_ONLY=18, EXECUTABLE=1, REMEASURED=3, ROLLBACK_PROVEN=0" |
| `ppa_contract_check` | `tools/ci/repo_hygiene_gates.sh` | `run_tolerating_uncheckable` | **rc 2** `[CANNOT CHECK] … contract.json: absent` |
| `ppa_measurement_check` | `tools/ci/repo_hygiene_gates.sh` | `run_tolerating_uncheckable` | **rc 2** `[CANNOT CHECK] INPUT_ABSENT: no such bundle` |
| `ppa_feasibility_check` | `tools/ci/repo_hygiene_gates.sh` | `run_tolerating_uncheckable` | **rc 2** `[CANNOT CHECK] candidates not found` |
| `ppa_pareto_check` | `tools/ci/repo_hygiene_gates.sh` | `run_tolerating_uncheckable` | **rc 2** `[CANNOT CHECK] candidates not found` |
| `ppa_problem_integrity_check` | `tools/ci/repo_hygiene_gates.sh` | `run_tolerating_uncheckable` | **rc 2** `[CANNOT CHECK] baseline …: absent` |

### Why the split, per program

**`closed_loop_executable_coverage_check` → `run`.** Its subject is the shipped
flow document. That is a repo-wide invariant needing no PR context and no design
run — the thing `repo_hygiene_gates.sh` says in its own header that it is for —
so it sits beside `flow-gate enforcement audit` and `stage membership declared
once`, which read the same file. It asks the question `closed_loop_edge_check`
explicitly stops short of: not "is this edge well-formed" but "is there CODE
that can take it, and what does that code prove". It has a real denominator, it
prints it, and there is no state in which it could not look — so
`run_tolerating_uncheckable` would be giving an rc 2 somewhere to hide.
Blocking from its first run is affordable and that was checked, not assumed: the
census is green today and the 18 DECLARED_ONLY edges are REPORTED, not failed.

**The other five → `run_tolerating_uncheckable`.** Each validates a RECORD, not
a design — a contract, a candidate set, a published frontier, a coverage bundle,
a pair of contracts — and this repository has filed none of them. Against an
absent record every one is rc 2 with the missing file NAMED; not one exits 0 on
an input it never opened. That is exactly the channel `run_tolerating_uncheckable`
exists for, and the ruling already stood three lines above them: vibe-ic#1241
wired `ppa_head_to_head_check` this way for the same reason, in the same file,
for the same family. These five are wired directly beneath it.

### Why NOT the flow YAML — measured, not asserted

No flow step produces any of these five documents, so a clause would have to
name a path nothing writes. Probed by actually wiring two of them at step 36
as `optional_program_exit_zero`:

    test_d2_gate_has_a_reachable_fail[step36] FAILED
    step 36: 2 blocking clause(s) reached no content-earned FAIL …
      'ppa_contract_check --contract reports/ppa/contract.json …'    -> VACUOUS_PASS
      'ppa_measurement_check --coverage reports/ppa/coverage.json …' -> VACUOUS_PASS

d2 materialises an unmet `condition_files_exist` as `{}`, and `{}` is rc 2 to
every one of these gates. The two ways out were five reddening fixtures over
synthetic contract sets, or five `UNREDDENED` registrations — and registering a
gap this landing created is the one thing that register is not for. The probe
was reverted; the flow YAML on this branch is byte-identical to the stack's.
Promoting these five into the flow is a flow-owner change with its own fixtures.
It is a REQUEST below, not something done quietly here.

### Limit, stated rather than left to be found

The five take an EXACT path, not a corpus walk, so unlike the head-to-head gate
they do not follow `$VIBE_IC_BENCHMARK_DATA`, and a record filed under another
name is not judged. The refusal is at least self-describing — it prints the path
it opened, so "I looked here and it was not there" is legible. The honest fix is
a `--corpus` mode resolved through `_corpus_location`; that is lane-owned code
this landing may not edit, so it is a REQUEST below.

### After

    gate_is_wired_check          unwired 59 (baseline 59); 1 new: closed_loop_edge_check
    checker_execution_wiring     test-only 35, baseline 34; 1: closed_loop_edge_check.py

Identical, by name and by number, to `867de4289`.

---

## 3. ITEM B — the declaration was true, at byte 8249, where the audit cannot read it

`flow_gate_enforcement_audit` on the stack:

    [FAIL] 3 NEW gate(s) are AUDIT_ONLY and declare no intent at all
       undeclared::area_total_vs_budget_check
       undeclared::ppa_head_to_head_check
       undeclared::tapeout_docs_gen

On `867de4289` the same audit fails with **exactly the other two**, so
`ppa_head_to_head_check` is the stack's one addition and the other two are base
debt.

And the finding was a false description of a real decision. The gate DOES
declare its intent — twelve lines of it, correct, including why `advisory` is
this audit's token for "no runner spawns it inline" and is NOT a licence to
ignore the verdict, and why the gate is nonetheless in step 36's BLOCKING slot.
`declared_intent` scans `text[:4000]`. The declaration sat at byte **8249**.

Fixed by moving the block verbatim to the top of the docstring, plus one
paragraph recording *why* it lives there, so the next reader does not tidy it
back down to where it reads well and is never seen. Nothing about the gate's
behaviour, wiring or verdict changes.

After: 2 NEW — `area_total_vs_budget_check`, `tapeout_docs_gen`. Identical to
main. Those two are deliberately untouched: deciding them changes what a real
run blocks on, which is the flow owner's call.

---

## 4. ITEM C — the pointer, registered as history

    programs/tests/test_ppa_contract.py:689  ghcr=0.3.18  (want 0.3.16)
      -- unregistered live pointer; add to INSTALL_DOC_CANDIDATES or
         .image-version-ignore

`.image-version-ignore`, per the gate's own message and per every entry already
in that file. The line is a `docker image inspect` that was actually run, with
what it returned recorded beside it: two different image ids carrying the same
`org.opencontainers.image.version`, inherited from the upstream base rather than
set by the fork — which is why the contract's toolchain identity is built on the
digest and not on the label.

Two independent reasons it must not be rewritten to the anchor. Advancing the
tag would attribute an inspection to an image it was never run against. And the
record's force comes from the two tags DIFFERING: collapsing either onto the
anchor deletes the comparison that establishes the label cannot tell two
toolchains apart, which is the defect the test reproduces. Nothing pulls it —
the test builds contracts from hand-written declarations and never starts a
container.

Bounded by the exact path, per that file's own rule. The entry says in its own
text that it is TEMPORARY: a separate lane is removing the coupling this net
polices, and when that lands the entry should be deleted with it.

After: 1 finding, `crosslayer_rewrite_equivalence.py:379 ghcr=0.3.15` —
identical to main, which fails this gate with exactly that one.

---
## 6. REQUESTS TO THE LANDER

### 6.1 THE HYGIENE BASELINE — the decision this branch was forbidden to make

`gate_is_wired_check` prints, on BOTH arms, unchanged by anything here:

    [NOTE] baseline shrank — now wired: analog_liberty_nonzero_delay_check.
    Re-run with --write-baseline.

**No baseline was written, on any gate, including when the gate asked.** The
note is left standing.

For the record, so the decision is made with the facts: this branch does NOT
make that note larger. The six programs wired in §2 were never IN
`gate_is_wired_baseline.json` — they are new files — so wiring them removes them
from the live unwired set without touching the recorded one. The unwired count
goes 65 → 59 against a baseline of 59, and the one name in the shrink note is
the same `analog_liberty_nonzero_delay_check` that main prints today.

A shrinking baseline is an improvement being recorded, not a failure being
hidden. Writing it is still the owner's call, and it is not made here.

### 6.2 `closed_loop_edge_check` — base debt, one line from the wiring above

Red on pristine `867de4289`, and `docs/PPA_CURRENT_STATE.md` §5 documents it as
such. It is the seventh name both wiring audits report, and it is the reason
both of them still exit 1 on this branch — deliberately, so the by-name hygiene
comparison against main has the same nine failing gates on both arms.

It is one line from the gate wired in §2, and the same rc was measured: **rc 0**,
"checked 22 declared closed_loop edge(s) over 69 step(s); every edge resolves to
a declared step, closes a loop, carries a trigger, and leaves a step whose gate
can produce a verdict."

    run "closed-loop edges resolve" "$ROOT" python3 "$PG/closed_loop_edge_check.py"

Adding that line takes `checker execution wiring` and `gates are wired to
something` from FAIL to PASS and the hygiene suite from 9 failed to 7 — better
than the bar, and a different denominator from the one this branch was measured
against. Deliberately left to the lander, because closing two of main's own reds
inside a wiring landing changes what the next A/B compares to.

### 6.3 `tools/ci/protected_landing_transition.json` must be re-rendered

`tools/ci/repo_hygiene_gates.sh` is a pinned `authority` path in that manifest,
with its sha256 recorded in both `current` and `next`. §2 changes the file, so
the pin no longer matches the tree.

That manifest is explicitly lander-owned — "a hash list rendered against one
base; a text merge produces a manifest that matches no tree" — so it is NOT
touched here. It needs re-rendering against whatever base this stack lands on.
No hygiene gate reads it (it is a merge-time artefact of
`gatekeeper-verify-merge.sh`), so nothing on this branch reports the mismatch;
that is precisely why it is written down rather than left to be discovered.

The current transition id is `ppa-head-to-head-reachable-v1-next` → `retire-
37p5self-v1-next`, so this has been done for a PPA landing before.

### 6.4 Give the five PPA record gates a corpus mode (PPA lane owner)

`ppa_contract_check`, `ppa_measurement_check`, `ppa_feasibility_check`,
`ppa_pareto_check` and `ppa_problem_integrity_check` take exact document paths.
`ppa_head_to_head_check` takes `--corpus` and resolves it through
`_corpus_location`, so it follows `$VIBE_IC_BENCHMARK_DATA` to a cloned corpus;
the five do not, and a record filed under another name is not judged.

The wiring in §2 is honest about this and its refusal names the path it opened,
but the gate is weaker than its sibling for a reason that is not a decision
anybody made. A `--corpus` mode through the same seam closes it. That is
lane-owned code and was not edited here.

### 6.5 Promoting the five into the flow is a flow-owner change

If a flow step is ever given PPA campaign documents to produce, these five
belong at that step and not in the hygiene suite. That move needs five d2
fixtures — §2 measures exactly why — and each new blocking clause needs an
`ENFORCEMENT:` declaration inside the first 4000 bytes of its docstring, per §3.
Neither is a lander's wiring step.

### 6.6 The temporary `.image-version-ignore` entry

§4's entry says so in its own text: a separate lane is removing the
image-version coupling this net polices. When that lands, delete the entry with
it rather than leaving a registration for a net that no longer exists.

---

## 7. WHAT THIS BRANCH DELIBERATELY DID NOT DO

* **No hygiene baseline written**, on any gate, including where one asked.
* **No `UNREDDENED` registration.** The step-33 gap was closable and was closed.
* **No gate weakened** to make a test pass.
* **No plugin version bumped**; no manifest, README or INDEX counter touched.
* **The flow YAML is byte-identical to the stack's.** The step-36 probe in §2
  was reverted after it was measured.
* **`area_total_vs_budget_check` and `tapeout_docs_gen` left undeclared.** Both
  are base debt on the same audit as §3, and deciding them changes what a real
  run blocks on.
* **Nothing pushed to main.**
