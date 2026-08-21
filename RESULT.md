# The ninth dimension — `verdict_consumed`

Branch: `jm9/d9-verdict-consumed`
Base: `e36d81c0a` (`origin/main`, v1.11.33), fetched and cut 2026-08-21.

Every number in this file traces to a command recorded beside it. Anything I did
not measure says NOT_MEASURED.

---

## 0. Three claims in the brief that did not survive measurement

| claim | as given | measured | command |
|---|---|---|---|
| step population | owner said 68, brief said 69 | **69** | `python3 -c "from matrix_63x8 import flowref as F; print(len(F.step_ids()))"` |
| `v1.11.19..v1.11.47` landed this morning | brief | **NOT CONFIRMED** — `origin/main` tops out at v1.11.33 | `git log --oneline origin/main \| head -1` |
| `prose_polarity_consulted_check` motivates a flow-step dimension | owner | **it is not a flow gate** — 0 occurrences in the flow yaml | `grep -c prose_polarity_consulted_check flow/phase1_phase2_phase3.yaml` -> `0` |

The third is the one that matters, and it is in section 1.

---

## 1. STEP 1 — deriving the ninth, and where I disagree with the brief

### The eight, as each module actually states its question

| # | asks about | the question, from the module's own docstring |
|---|---|---|
| 1 `wiring` | the GATE | would anything real parse and execute this gate at run time? |
| 2 `falsifiable` | the CLAUSE | is there an input that drives this gate to a genuine FAIL verdict? |
| 3 `outputs_produced` | the ARTEFACT | does every declared entry resolve to a real, non-empty, non-symlink file? |
| 4 `criteria_match` | the GATE | does it read the artefact its step claims — not the wrong file? |
| 5 `deps_correct` | the GRAPH | is `blocks_on` the true upstream set — no missing, no phantom edge? |
| 6 `skip_discipline` | the TIER | is a skip conditioned on a runtime fact, and reported below PASS? |
| 7 `outputs_list_complete` | the LIST | does the step emit a load-bearing artefact it never declares? |
| 8 `missing_caught` | the CATCHER | when a declared output is missing, does `check_step` return MISSING? |

### What can be wrong that all eight call healthy

All eight stop at the STEP. Not one of them follows a step's FAIL outward to the
process exit code. Dimension 2 comes closest and explicitly stops at the clause:
it grades `_check_program_exit_zero` / `_check_files_exist` /
`_check_json_field_true`. Whether that clause's FAIL becomes the step's FAIL, and
whether the step's FAIL survives the verdict pass, are two further edges nothing
traverses.

**So I agree with the owner's question. I disagree with the evidence offered for
it, and the disagreement changes the scope of what I built.**

### The owner's evidence is about the landing process, not the flow

`prose_polarity_consulted_check` occurs **zero times** in
`flow/phase1_phase2_phase3.yaml`. It is invoked from
`tools/ci/repo_hygiene_gates.sh`:

```
$ grep -c 'prose_polarity_consulted_check' \
    vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml
0
$ grep -rln 'prose_polarity_consulted_check' --include=*.sh .
tools/ci/repo_hygiene_gates.sh
```

A hygiene gate red for 35 commits while landings continued is a hole in what
consumes `repo_hygiene_gates.sh`. **No per-flow-step dimension would have caught
it, and this one does not.** That is stated in the module docstring and in the
package README rather than left for a reader to discover, because a dimension
that let someone believe it covered the motivating case would be measuring
something adjacent and reporting it as if it answered the question — the disease
`matrix_63x8/README.md`'s "one rule" is about.

### The flow-side mechanism does exist, and I measured it

`flow_compliance_check` carries three live paths that take a real FAIL and drop
it before the exit code:

1. **`INFORMATIONAL_GATES`** — 4 entries. `_step_failure_is_informational_only`
   removes a step from `failing` when every FAIL reason cites one of them. Its
   own note on the `l25_…` entry names the risk: *"'advisory' becomes the same
   'FAIL and the flow continued anyway' mistake"*. Reachability proved against
   the real function:

   ```
   all-informational  -> True     # the step leaves `failing`
   mixed              -> False
   no informational   -> False
   ```

   Live today: **0 of 67** steps with resolved gate programs are in it. The
   mechanism is armed and no step currently sits in it — which is exactly when a
   guard is worth adding.
2. **`advisory_program_exit_zero`** — **37 of 213** clauses. A FAIL there never
   becomes the step's FAIL. Live today: **0** advisory-only steps.
3. **`structural_only_verdict`** — under `--phase 2 --strict-structural`,
   `scoped` collapses to `P0` plus the analog track and every other step's
   verdict is, in the module's own words, *"REPORTED but NOT factored into
   Overall"*.

### The alternative I considered and rejected

The README's own biggest disclosed gap is *"NO cell reads the CONTENT of the
artefact a step produces"*. I did not build that, for three measured reasons:
the `ARTEFACT_MUTATION` channel already addresses part of it; a separate landed
campaign (`tools/d9_content_census.py`, `d9_flow_gate_reality.py`, #1006) owns
the content-checker work; and the README states why it is not a matrix
predicate — *"needs a semantic model of each report format, which is per-gate
engineering"*. Consumption **is** a matrix predicate: uniform across steps,
derivable live, falsifiable by fixture.

---

## 2. STEP 2 — what was built

`programs/tests/test_matrix_d9_verdict_consumed.py`, importing the
`matrix_63x8` substrate. One cell per flow step, derived live from
`C.cells_for(9)`; no literal step list anywhere in it.

### The three legs

**L1 — BLOCKING REACH.** The step declares >= 1 clause whose FAIL can become the
step's FAIL. Live yaml.

**L2 — NOT DISCARDED AS INFORMATIONAL.** A real `StepResult` at FAIL, in the
reason grammar `_evaluate_gate` really emits, naming the step's OWN resolved gate
programs, handed to the REAL `_step_failure_is_informational_only`.

**L3 — REACHES THE EXIT CODE.** The real `flow_compliance_check.py` run as a
subprocess, `--strict`, two arms:

```
FAIL-tier {"files_exist": ["_d9_gate/absent.flag"]}   -> rc != 0, step FAIL
PASS-tier {"files_exist": ["_d9_gate/gate_ok.flag"]}  -> rc == 0
```

**P0 is measured on its OWN mechanism**, not a stand-in: it declares no `gate:`,
so an injected clause never reaches `check_step` (measured: SKIPPED-CONDITION in
both arms). Its L3 drives the real `_run_structural_rtl_gates` umbrella instead.
`matrix_cell_substitution()` reports that split, re-derived from the live yaml:
**68 SUBSTITUTED, 1 OWN**.

### Denominators — printed on every run, and refused if any goes to zero

```
  DIMENSION 9 (verdict_consumed) — live denominators
    steps                                  69
    gated_steps                            68
    gateless_steps                          1
    steps_with_resolved_gate_programs      67
    clauses                               213
    blocking_clauses                      176
    advisory_clauses                       37
    informational_gates                     4
```

### Cell states

**69 ENFORCED, 0 WAIVED, 0 NA.** No cell of this dimension is NA: every step
either declares a gate or is the structural umbrella, so "does its verdict reach
the exit code" is never a malformed question. An NA here would be a skip wearing
a hat.

The gaps this dimension cannot close are dimension-wide rather than per-cell, so
they are registered where the campaign registers dimension-wide gaps — the
module's `KNOWN GAPS` docstring section, as d3, d6 and d8 do — not as per-cell
waivers, which would misattribute a shared limit to arbitrary steps:

1. L3 measures the DEFAULT invocation; `--phase 2 --strict-structural` is an
   owner decision, pinned for SHAPE by
   `test_d9_structural_only_scoping_is_still_the_documented_two_member_set` so it
   cannot widen quietly.
2. L3's stand-in is a `files_exist` clause, so it exercises that consumption
   path, not `program_exit_zero`'s. They converge at `_evaluate_gate`'s return.
3. `test_d9_every_one_shot_runner_reads_the_checkers_returncode` proves by AST
   that each runner READS the checker's return code. It does **not** prove the
   branch taken on it aborts. Closing that needs a live runner invocation per
   runner — a phase-scale job, not done here.


---

## 3. THE A/B, BY TEST ID

Base: pristine worktree at `e36d81c0a` (`/home/reyerchu/AI_IC_design/_jm9_base`).
Head: `4ec69d6c5` on `jm9/d9-verdict-consumed`.

Both measured the same way, **per file and SERIALLY** — never `-n`, and never a
whole-selection total, because "55 red" and "55 red" can be different sets:

```
run_family.sh <tree> <tag>   # one pytest process per test_matrix_*.py, in order
ab.py base head3             # red set by TEST ID, diffed both directions
```

```
=== base : 55 red test IDs over 18 files
=== head3: 16 red test IDs over 19 files   (the 19th is d9, new)
--- FIXED (41) ---   red in base, green in head
--- NEW RED (2) ---  green in base, red in head
--- STILL RED (14) ---
```

Per file:

| file | base | head |
|---|---|---|
| `test_matrix_63x8_ledger` | **19 red** | 0 |
| `test_matrix_d1_wiring` | 1 | 0 |
| `test_matrix_d2_falsifiable` | 1 | 0 |
| `test_matrix_d4_criteria_match` | 1 | 0 |
| `test_matrix_d5_deps_correct` | 2 | 0 |
| `test_matrix_d6_skip_discipline` | 1 | 0 |
| `test_matrix_d8_missing_caught` | 4 | 0 |
| `test_matrix_63x8_figure_coverage` | 1 | 0 |
| `test_matrix_d3_outputs_produced` | 8 | 6 |
| `test_matrix_d7_outputs_list_complete` | 2 | 1 |
| `test_matrix_mutation_ledger` | 5 | 3 |
| `test_matrix_63x8_coverage` | 5 | 3 |
| `test_matrix_63x8_census_freshness` | 5 | 3 |
| **`test_matrix_d9_verdict_consumed`** | — | **0 of 79** |

### The two NEW REDs, and neither is a regression

**`census_freshness::test_no_substituted_cell_is_inside_a_figure_presented_as_enforcement`**
— the published census block says 49 substituted; the tree now measures 117.
`117 = 49 (d8) + 68 (d9)`, which is d9's substitution contract working exactly as
designed. The block is stale, not wrong-headed, and it closes with one run of the
generator (see REQUESTS 4).

**`coverage::test_nested_outcome_run_outlives_old_fixed_bound_with_semantic_progress`**
— NOT a regression. It is red on BASE too; the base family run's green was a
FALSE GREEN. Measured in isolation, serially, on an idle host (load 2.9):

```
_jm9_base: pass=0 fail=8 of 8
_jm9_wt  : pass=0 fail=8 of 8
```

Its own diagnostic is `WATCHDOG_STALLED: ... did not advance for > 0.45s —
killed as hung, not slow`. A 0.45 s forward-progress window on a self-test that
spawns a 2-way concurrent driver is a bound, not a verdict. Caught only because
the bar says re-run every candidate red serially before acting on it; a single
sample on each side would have filed this as damage I did.

### Mutation arm for each fix

Every fix ships with the arm that reddens it. Where the arm is a committed test
it is named; where it was a one-off replay the command and its verdict are
recorded.

| fix | arm |
|---|---|
| d9 L1 (blocking reach) | `test_d9_l1_reddens_when_a_steps_only_blocking_clause_goes_advisory` — demotes every clause of a live step to advisory in a SCRATCH yaml |
| d9 L2 (informational discard) | `test_d9_l2_reddens_when_a_steps_whole_gate_set_becomes_informational` — monkeypatches `INFORMATIONAL_GATES` on the REAL module |
| d9 L3 (exit code) | `test_d9_l3_control_arm_discriminates` — FAIL-tier must exit non-zero AND PASS-tier must exit zero, both directions |
| d9 mechanism liveness | `test_d9_the_informational_exclusion_is_reachable_at_all` — proves the real function still discards, with a synthetic gate name |
| d9 umbrella carve-out | `test_d9_exactly_one_step_declares_no_gate` |
| d9 runner scan | `test_d9_the_invocation_scan_ignores_prose` — pins the discrimination a text scan lost |
| d8 survival clause | `test_the_survival_clause_is_load_bearing_and_narrow` — revert it and `1.6x` re-enters as blind; widen it and the newly un-graded step is named |
| d6 disclosure prefix | `test_d6_every_tier_moving_hint_is_either_accepted_or_excluded_by_name` — found `__NA_HINT__` and `__SUBSTANTIVE_HINT__` on first run |
| d2 `1.6x` fixture | the cell itself: `_f_crosslayer_refuted` -> rc 1, `CLX_NOT_EQUIVALENT`; without it the clause reaches PASS |
| ledger `1.6x` x7 | `matrix_mutation_ledger.py --replay <NAME> --step 1.6x` -> REDDENED, seven times, timings in the commit body |
| d9 outside the ledger | `test_the_ledger_names_every_dimension_it_does_not_cover` — both directions |

### STEP 3 — the 17, and what I can honestly say about them

The brief asks which of "the 17 left with written reasons" are still red. **I
was never given that list**, and I did not find it: `findings92.md` was present
in the session-start `git status` and had already been deleted from
`/home/reyerchu/vibe-ic` by the time I looked, and no handoff note names them.
So I cannot report against that set, and I am not going to guess which 17 of my
55 they were — a mapping I invented would read like coordination and be fiction.

What I can report is the set I measured myself, by test ID, on both sides. It
is above. If the other agent's 17 are a subset of my base-55, the diff already
answers the question; if any of them were outside the `test_matrix_*` family,
my sweep never looked at them and says nothing about them.

One coordination fact IS worth passing back: **the "ONE d8 red" the brief says
seven others were blocked behind is closed.** It was
`test_a_readable_artefact_that_is_wrong_is_not_worth_the_same_as_a_right_one`,
and its own message demanded a fix rather than a pin. The demand was right and
its diagnosis was wrong — no gate had stopped reading; step `1.6x` declares as
its only output the path its own gate writes. See 4.3.


---

## 4. What I fixed that was ALREADY RED on main

None of this was collateral of the ninth dimension. Each was red on
`e36d81c0a` before this branch existed, and each is verified against the
pristine base worktree `/home/reyerchu/AI_IC_design/_jm9_base`.

### 4.1 The step population moved and the pins did not

Three different populations coexisted on `origin/main`:

| source | said |
|---|---|
| `test_matrix_63x8_coverage.GRID_AS_MEASURED` | **67** steps |
| `STEP_IDS_AS_MEASURED`, beside it in the same file | **68** ids |
| `matrix_63x8/README.md` anchored figure | **68** |
| the live yaml | **69** |

`GRID_AS_MEASURED` and `STEP_IDS_AS_MEASURED` are meant to move together and
had been moved half-way, so the count was wrong before I touched anything.
Delta against the pinned id list: `+0.5ic`, `+1.6x`, `-37.5self` — 68 + 2 - 1 =
69. `1.6x` landed in v1.11.15, `37.5self` retired in v1.11.18, and the pins were
restated for the departure only.

Repaired, each re-derived by running its own accessor rather than by arithmetic:

* `GRID_AS_MEASURED` -> `(69, 9, 621)`, `STEP_IDS_AS_MEASURED` -> the live 69
* five `CENSUS_*` population pins in the ledger
* per-dimension partition pins in d3 (x3), d4 (x2), d5 (x2), d7 (x3)
* d3's hand-restated state triple `(51, 2, 15)` -> `(52, 2, 15)`, naming the
  cell that moved (`1.6x/d3`, arriving ENFORCED) and each clause of that
  reading re-derived
* 44 anchored figures, via `tools/gen_matrix_63x8_census.py --fix-figures`

### 4.2 A tripwire that was BORN red

`test_output_entries_classify_into_the_four_kinds` pinned `sum == 161`,
`FILE == 119`. The tree says 162 / 120 — and said so **at the commit that wrote
the pin**, `867de4289` (v1.11.18):

```
$ git diff 867de4289 origin/main -- flow/phase1_phase2_phase3.yaml
$ git diff 867de4289 origin/main -- .../matrix_63x8/flowref.py | grep -i classify
```

Both empty. Neither input has moved, so the count then was the count now. The
comment block's own itemisation does not reach its own total either: `114 + 2 +
1 + 2` with `37.5self`'s `-1` dropped gives 118, the line states 119, the tree
said 120.

This is a different failure from drift. Drift means the tree moved and the pin
did not. This pin never matched the tree it was written against.

### 4.3 Step 1.6x arrived with a gate nothing had shown could fail

Four separate reds, one subject.

**d2 — the gate banked a PASS.** Its single blocking clause answers
`NOT_APPLICABLE` on the EMPTY fixture and exits 0. EMPTY cannot reach its FAIL
by design: the gate's own docstring records that it was first written
CONDITIONAL and `flow_condition_reachability_check` refused that shape — *"a
check disabled by exactly the situation it was written for"*.
`_f_crosslayer_refuted` makes a search look ATTEMPTED and REFUTED, which is the
step's own `closed_loop` trigger. MEASURED rc 1, `CLX_NOT_EQUIVALENT`, through
the program's own status ladder — not by malforming the file, which would prove
only that the gate can crash.

**d6 — the disclosure was not recognised.** L1b read the disclosure prefixes
live from `flow_compliance_check` "so a renamed prefix is noticed", but the LIST
was three literals and the consumer has had a fourth since
`__JSON_VACUOUS_HINT__` was introduced. It is the PREFERRED channel, not a
lesser one: the consumer dispatches it in the same `elif` chain (~8099), reads
it for the VACUOUS_PASS tier (~10040), and raises it from the gate's `--json`
report for the reason #887 records — *"a disclosure a project-path length can
delete is not a disclosure, and stdout is exactly that channel"*.
MEASURED: L1b fires on `['1.6x']` with three prefixes, `[]` with four, nothing
else moves.

**d8 — the artefact could not survive to be graded.** `1.6x`'s only declared
output IS its gate's `--json` target, so the gate WRITES it during
`_evaluate_gate` and the wrong body is gone before the output bookkeeping opens
it. Reproduced directly: `verdict` goes `"FAIL"` -> absent, bytes differ.
UNMOVED there means "the gate overwrote the file", not "the gate read it and did
not care", and telling those apart is the whole point of the content arm.

**d1 — two declared programs nothing dispatches.** v1.11.15's message was "wire
step 1.6x to an executor"; what was wired is the JUDGE.
`design_one_shot_runner` dispatches the constant
`"crosslayer_rewrite_equivalence_check.py"` (AST-confirmed, line 8457) and its
own docstring says so: *"Runs the JUDGE ..., never the tool"*.

---

## 5. Three defects I put into my OWN module and had to take back out

Recorded because two of them are the exact disease this campaign exists to
stamp out, committed inside the module written to warn about it.

1. **The control arm caught a harness that certified everything.** Writing RTL
   into the L3 fixture makes `flow_compliance_check` inject the P0 structural
   umbrella into a one-step run. On a synthesized tree that umbrella FAILs and
   P0 is unconditionally inside `scoped`, so the run exited 1 whatever the step
   under test did. MEASURED: step D1 resolved PASS and the run still exited 1,
   on P0's verdict. Without the PASS-tier control arm, all 68 cells would have
   been green on P0's failure.
2. **A mutation arm that did not mutate.** L1's arm rewrote only top-level gate
   keys; every real gate is `{"all_of": [...]}`, so it changed nothing while
   reporting a successful mutation — certifying the leg it was meant to test.
3. **A text scan, and then an adjacent measurement.** The runner test first read
   raw file text for `flow_compliance_check` and treated a hit as an invocation:
   5 of 7 runners name it in PROSE only, so three were graded as consumers of a
   verdict they never ask for. That is the PR #460 trap. Corrected to AST, it
   then asked whether `.returncode` appeared anywhere in the enclosing function
   — and matched one belonging to a DIFFERENT subprocess in the same 200-line
   function.

---

## 6. A live finding at the flow's outer edge

`phase3_one_shot_runner.py:40884` runs `flow_compliance_check.py … --strict`
like this:

```python
try:
    _sp_fc.run([sys.executable, str(PROGRAMS_DIR / "flow_compliance_check.py"),
                str(project), "--strict"], check=False, capture_output=True, text=True)
except Exception:
    pass
```

Result unbound, `check=False`, bare `except: pass`. The comment above it calls
this *"This direct, BLOCKING flow_compliance re-run."* Its exit code is consumed
by nothing.

On the happy path the verdict IS consumed — through the file, via
`_derive_headline_verdict` reading the refreshed
`phase23_completion_audit.json`. On the crash-or-timeout path the `except`
swallows it, the PREVIOUS run's audit json stays on disk, and
`_derive_headline_verdict` has an absent/unreadable branch but NO stale branch —
so a stale verdict reads as a fresh one. The call site's own comment says the
refresh is what stops the headline "lagging its own sign-off"; on that path it
lags exactly, and silently.

RECORDED, NOT FIXED. It is pinned as the `REPORT` channel in
`RUNNER_CONSUMPTION_AS_MEASURED` with the weakness written beside it. Changing a
runner's verdict plumbing is a flow-level change and needs a change that carries
its own acceptance evidence.

---

## 7. What I could NOT settle

Four items. None is hidden behind a relaxed test, a widened waiver or an edited
fixture.

### 7.1 Six d3 cells cannot be measured on this host — and must NOT be waived

`test_d3_required_outputs_are_produced[step15|17|19|20|30|32]` were red on base
and are red here. Their manifest records cite run roots of `kind: "home"` —
`campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721` and siblings — which
resolve on the campaign host and **nowhere on this one**:

```
$ ls -d ~/campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721
ls: cannot access ...: No such file or directory
$ find ~ -maxdepth 4 -type d -name 'pdk_portability_ihp-sg13g2_20260721'
(nothing)
```

The test offers three closures: re-point the record, publish a run tree, or
waive. **I deliberately did none of them.** A waiver whose premise is "the
corpus is not on my machine" is a HOST-dependent decision, and #527 removed
exactly that class from this dimension — *"its answer must be the same on every
host"*. Waiving here would re-open the defect the campaign closed, and it would
buy a green with the one currency this suite refuses.

They are NOT MEASURED. On a host carrying the corpus they may well be green;
nothing here measured that either, so nothing here says it.

### 7.2 Pointing at the corpus makes d3 MORE red, not less

Worth recording because the obvious next move looks like a fix and is not.
With `VIBE_IC_BENCHMARK_DATA` pointed at a clone carrying 16 ICs, d3 goes from
**6 red cells to 9** — `0.5ic`, `1.6x` and `31` join. The corpus-absent skip was
masking real failures. The unpointed run is what CI does, so the unpointed
number is the one this report quotes; the pointed one is recorded here so nobody
"fixes" the six by setting a variable and reports a smaller red set.

(Verified the corpus was not written to: `git status --porcelain benchmark-data`
returned 0 lines before and after every run against it.)

### 7.3 Three mutation-ledger tests, on one cause

`0.5ic/d3` and `1.6x/d3` are ENFORCED with no measured mutation, and cannot get
one: both return `ALREADY_RED (baseline_rc=1)`. Section 5 of the ledger commit
records the two design gaps this exposed — the `NOT_FALSIFIABLE` register the
error message recommends does not actually satisfy the aggregate, and `census()`
has no state for a cell whose predicate is currently red. Both are changes to
the ledger's core semantics.

### 7.4 `d7/step31` is a real flow defect and I did not change the flow

`reports/phase3/drc_signoff.json` is written by `drc_report_check` and read by
`general_precheck`; step 31 declares neither. That is W1 — a load-bearing
artefact nothing declares, so nothing checks it exists, so its absence is
invisible. It is likely NEW as of v1.11.18, which moved the general precheck
into 37.5ic's second arm.

Adding it to `required_outputs` makes it UNCONDITIONAL: a run that stops
producing it goes MISSING. That is probably the right outcome, but it is a flow
change with blast radius across every published run, and it belongs in a change
carrying its own acceptance evidence rather than at the end of this one.

---

## 8. REQUESTS TO THE LANDER

1. **No protected path moved.** `tools/ci/repo_hygiene_gates.sh` is untouched,
   so `tools/ci/protected_landing_transition.json` needs no render from me. I
   did not edit that manifest.
2. **No version bump.** `VERSION` is untouched; the lander assigns it.
3. **No `--write-baseline` was run**, on any gate, including where a gate asked.
4. **The census block is NOT regenerated**, and it cannot be from this branch:
   `tools/gen_matrix_63x8_census.py` refuses with NORECORD while any non-cell
   matrix test is red, and 7.3's three are non-cell. Once those close, one run
   of `python3 tools/gen_matrix_63x8_census.py` turns the three
   `census_freshness` reds green — they are all the one stale block. The
   anchored figures ARE regenerated (`--fix-figures`), which is the half that
   was in reach.
5. **A decision I would like taken above me: `d7/step31`** (7.4). Declare
   `reports/phase3/drc_signoff.json` on step 31, or record why it stays
   undeclared.
6. **A second decision: dimension 9 in the mutation ledger.**
   `LEDGER_DIMENSIONS_NOT_COVERED` declares the gap with a reason and pins it in
   both directions. Registering d9 properly needs a measured `applies_to` sweep
   over 69 steps per mutation shape. It is a discrete, schedulable job.
7. **`phase3_one_shot_runner`'s discarded exit code** (section 6) — recorded as
   the `REPORT` channel, not fixed. If you want the crash path closed, the fix
   is a staleness check in `_derive_headline_verdict`, not a plumbing change.

---

## MERGE ONTO v1.11.51 (by the matrix substrate owner)

This branch was cut at v1.11.33, before `jmatrix/63x8-main-reds` landed as
v1.11.44. Four of its six commits are INDEPENDENT re-derivations of the same
findings; three dropped as already upstream on rebase. The branch is not wrong,
it is early — and where the two lanes disagreed, a test decided, never a
preference. Per file:

| file | kept | what decided it |
|---|---|---|
| `test_matrix_63x8_ledger.py` | **both notes, jm9's constants** | jm9 owns the DIMENSION axis (`DIMS 8→9`, `CELLS 552→621`); the landed note owns the STEP axis. Independent, so keeping only the later note loses why the earlier number moved. |
| `test_matrix_63x8_ledger.py` (entries) | **neither — re-derived** | landed 163/121, jm9 162/120, the live tree **164/122**. A third entry (step 31 `drc_signoff.json`) landed after both notes. |
| `test_matrix_d2_falsifiable.py` | **jm9's fixture**, duplicate key removed | Both lanes wrote a `CLAUSE_FIXTURE` entry under the SAME dict key — the second silently won, the first was dead code reading as live. Both redden, neither is `ABSENCE_RED`; jm9's reaches `CLX_NOT_EQUIVALENT`, the relation the step exists for, through the program's own status ladder. |
| `test_matrix_d8_missing_caught.py` | **jm9's reading** | Its own `test_the_two_readings_of_self_written_agree`, written for this merge, decided it. |
| `matrix_mutation_ledger.py` | **landed notes** | Eight conflicts, all comment-style; both lanes recorded REDDENED for the same twelve mutations. The landed notes carry the replay timings. Verified: 12 mutations carry `1.6x`, `measured.reddened == len(applies_to)` for every one. |

### The d8 decision, because it went against the substrate owner

Two lanes answered "is this row gradable?" two ways — yaml INFERENCE
(`_gate_written_paths`) and on-disk MEASUREMENT (`_survived_the_gate`). They part
on step 2:

    step 2    reports/phase2/lint/rtl_hygiene.json
              the gate command NAMES it as a --json target   (inference: not gradable)
              the file SURVIVED the gate on disk             (measurement: gradable)
    step 1.6x named, and did NOT survive — both readings agree

A `--json` flag is an intention; only the disk says what happened. The inference
over-predicts for any clause whose program does not run. So
`CONTENT_ARM_UNGRADABLE_SELF_WRITTEN` drops to `("1.6x",)` and step 2 goes BACK
into `CONTENT_ARM_BLIND` — removing it was the substrate owner's error, and the
measurement restores it. The divergence itself is pinned in BOTH directions so
the test still fires for a new one; its message anticipated one direction and the
measured case is the other.

### Measured

Nine-dimension census regenerated: **621 cells, 621/621 accounted**, 60 anchored
figures fresh. `test_matrix_d8_missing_caught.py` 347 passed.

By TEST ID over all `test_matrix_*` files, serially in the container:

| | failed | passed |
|---|---|---|
| bare `origin/main` v1.11.51 | 39 | 1119 |
| this branch | **34** | **1209** |

**Introduced: 0** (`comm -13` empty). **Closed: 5** — the three census-freshness
IDs, the figure-coverage ID, and the entries pin. The 34 that remain are red on
bare main and are outside this lane.

`git diff --stat origin/main..HEAD` is 16 files — lane-sized.
