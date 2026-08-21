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

