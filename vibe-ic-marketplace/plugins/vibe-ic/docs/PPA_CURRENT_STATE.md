# PPA — what is actually true today

Re-measured on **2026-08-24** against **`e265f228b`** (plugin version **1.11.72**),
on the machine that ships the plugin, with the commands quoted beside every
number. Nothing here is quoted from a plan, a spec or an earlier document. Where
a number contradicts a planning document, the number is what this file records
and the contradiction is named.

This file exists because the PPA enhancement is being built by twelve authors at
once against a shared picture of the starting state, and a starting state that
is eight versions stale sends people to fix things that are already fixed and
leaves the ones that are not. Re-measure it before trusting it; the commit is
stamped above so you can tell how old it is.

---

## 1. The closed-loop census — 21 declared edges, 18 of them a line of YAML

```
$ python3 programs/closed_loop_executable_coverage_check.py
[PASS] closed_loop_executable_coverage_check: 21 declared closed_loop edge(s)
       over 68 step(s); DECLARED_ONLY=18, EXECUTABLE=0, REMEASURED=3,
       ROLLBACK_PROVEN=0
```

The four classes are nested tiers, not a palette. Each subsumes the one before
it, so a claim at tier N carries the evidence of every tier below it:

Promotion evidence is executable AST structure, not a label or a file-presence
claim. In particular, the actuator callee must match the canonical runner
entrypoint for the YAML edge's actual `fallback_to`, and the source step's own
trigger result must control that fallback on the same live path. A sibling edge
that shares the same fallback target cannot lend its retry loop;
the required trigger polarity is pinned, overwritten receipts and code after
path terminators are rejected, and REMEASURED requires a post-fallback call or
a reachable loop back-edge into the measurement. `actuation_form: re_execute`
cannot promote an unrelated call by itself.

| class | what it asserts |
|---|---|
| `DECLARED_ONLY` | the flow declares the edge and **nothing re-enters the fallback step** when the trigger fires |
| `EXECUTABLE` | a named program re-enters the fallback step when the trigger fires; refusing a candidate is blocking, not execution of the edge |
| `REMEASURED` | EXECUTABLE, **and** the same program re-measures the metric the trigger names afterwards |
| `ROLLBACK_PROVEN` | REMEASURED, **and** it can undo its actuation when the re-measurement is worse, **and a named test proves the undo** |

| step | fallback | class | why |
|---|---|---|---|
| `4` | 1 | REMEASURED | `design_one_shot_runner.main` re-runs `step_rtl_gen` on a reference-TB failure and re-runs the testbench. Bounded by `--max-rtl-repair-retries`; stops on byte-identical RTL with `FAIL_RTL_REPAIR_INERT`. |
| `23` | 32 | REMEASURED | the post-route timing-repair trigger in `phase3_one_shot_runner.step_canonicalize_artefacts`: `_run_postroute_timing_repair` then `_measure_postrepair_mcorner_ocv`. |
| `32` | 32 | REMEASURED | the same actuator; step 32 is where it runs. |
| `2` | 1 | DECLARED_ONLY | cross-layer fidelity now belongs to Step 2. Its judge rejects a bad candidate, but PRE/POST runtime spies both measured zero re-entry into `step_rtl_gen`; rejection must not be reported as an executable fallback. |
| `3`, `5`, `8`, `9`, `10`, `13`, `14`, `20`, `24`, `25`, `26`, `27`, `28`, `31`, `33`, `A7`, `A9` | — | DECLARED_ONLY | no actuator found in any runner. |

### The zero is the load-bearing number

`ROLLBACK_PROVEN = 0`. The step-32 repair **does** implement an undo — on a
measured setup regression it sets `timing_repair_reverted_regression` and retains the
pre-repair artefacts — and

```
$ grep -rn 'timing_repair_reverted_regression' programs/tests/
(no files)
```

so nothing proves it works. `test_postroute_timing_repair_audit.py` tests the *audit* of an
already-regressed record, which is a different claim.

### Three DECLARED_ONLY entries that are worth reading individually

* **`31 -> 32`** (physical verification falls back to the repair pass) cannot be
  taken **by design**, and the repository says so: `postroute_timing_repair_status_gen.py:183` —
  *"A non-timing sign-off domain FAILED; the timing-repair pass does not apply."*
  The auto-trigger is keyed on multi-corner OCV timing only, so a DRC or LVS
  failure can never actuate step 32.
* **`A7 -> A3` and `A9 -> A3`.** `analog_one_shot_runner.py` contains **zero
  `While` nodes** (AST, not grep: 0 `While`, 7 `For`, and the seven iterate over
  blocks). No call site in it re-runs a prior analog step — the only step-ish
  callees are `_step_outputs` and `emit_steps_view`, both reporters. The analog
  convergence story is two lines of YAML.
* **`33 -> 17`** is the newest edge (power finally got one; area still has none)
  and its gate REFUSES with rc 2 when `L19.power_budget_uw` is undeclared, so on
  a design that declares no budget the edge is not merely untaken — it is
  unreachable, honestly.

### A real loop that serves no declared edge

`design_one_shot_runner.main` carries a **second** `while True:` — a
`step_usb_hid_tester_verify` failure re-runs `step_rtl_gen`, re-simulates,
recompiles and re-burns. Step 11 (DFT insertion / board test) declares **no**
`closed_loop`. So the flow has 18 declarations nothing takes and one loop
nothing declares. Both halves of the same gap.

### Who reads any of this

`closed_loop_edge_check` (well-formedness) is called from
`programs/tests/test_matrix_d5_deps_correct.py` — dimension 5 of the 63x8 matrix
— and from **no flow gate clause**. `closed_loop_executable_coverage_check`
(this census) has none either. See §5.

---

## 2. The step-32 blast radius — three documents, none of which agreed

Measured before the fix:

| source | said |
|---|---|
| `phase3_one_shot_runner.py:33408` | `"affected_steps": [21, 23, 24, 29, 30]` |
| flow step 32 `closed_loop.trigger` | `"Aggregator: re-run #21-#28 after post-route timing repair"` |
| flow step 32 `blocks_on` | `[23, 24, 25, 26, 27, 29, 30, 31]` |

and **nothing read any of them**. `postroute_timing_repair_audit.py:337` asks
`if "affected_steps" not in data` and stops there, so `[]` and `[999]` were both
clean. `git log -S` puts the literal in `0a9e51577`; no test asserted it in the
~300 versions since.

The repair rewrites the routed implementation — multi-corner `repair_design` +
`repair_timing -setup` + `detailed_route`, then its own re-extraction — which is
step 21's output. So the evidence that no longer describes the design is

```
{21} u descendants(21) - descendants(32) - {32}
```

over the flow's `blocks_on` graph. Read it as: everything downstream of routing
whose result describes the **pre-repair** implementation, minus what is
downstream of the repair and therefore consumes its result by construction.
(Step 33, power, is in for exactly that reason — it depends on 23, not on 32, so
nothing in the graph guarantees it ever sees the repair. Metal fill and GDSII are
out for the mirror reason.)

```
21  22  DT2  DT3  23  24  25  26  26.5ic  27  28  29  30  31  33
```

The two the old literal omitted and that matter most: **22** (parasitic
extraction — the repair re-extracts, which is itself proof the old SPEF is
stale) and **31** (physical verification — the repair changes geometry *and*
netlist, so DRC and LVS are both invalidated).

The literal now ships derived, and
`programs/tests/test_closed_loop_executable_coverage_affected_steps.py`
recomputes the set from the shipped flow on every run, so the two cannot drift
again. The flow's `#21-#28` prose is still wrong and is a lander request; the
test asserts the *disagreement* and goes green the moment the prose is corrected.

**`affected_steps` is a requirement, not a receipt.** The runner re-runs none of
those steps, which is why the repaired netlist is not the shipped implementation —
`step_gds` (25060) → `step_drc` (26523) → `step_lvs` (27191) all run *before*
`step_canonicalize_artefacts` (31726), where the repair fires. The repository
already says this in `docs/architecture/ALL_STEPS_v1.4.14.md:140`: *"NOT an ECO:
it re-routes the whole design rather than preserving the implementation."*

---

## 3. The PPA program surface

```
$ ls programs/ | grep ppa
_ppa/  ppa_area_threshold_check.py  ppa_head_to_head_check.py
ppa_predict_aggregate.py  readme_ppa_extractor.py
```

| program | flow clause | called by a runner | test files |
|---|---|---|---:|
| `ppa_area_threshold_check` | none | none (only `benchmark/cvdp_gate.py`) | 10 |
| `ppa_head_to_head_check` | **step 36**, `optional_program_exit_zero` | none | 1 |
| `ppa_predict_aggregate` | none | none | 2 |
| `readme_ppa_extractor` | none | `phase1_doc_one_shot_runner.py` | 1 |

`ppa_head_to_head_check` is wired, and its clause is conditioned on
`**/*head_to_head*.json` existing — which the flow's own
`absent_condition_reason` explains is deliberate: *"The subject is a CLAIM, not a
result … nearly every sign-off legitimately files none."* So it is wired and, on
an ordinary design run, silent. Both facts are true and neither implies the
other; a plan that reads "wired" as "exercised" will be wrong.

`ppa_area_threshold_check` has **ten** test files and **zero** production
callers. Test count is not wiring.

---

## 4. The `_ppa/` module map — 1 of 18 exists

`docs/PPA_INTERFACES.md` §4 declares eighteen modules plus a `backends/`
package. On disk:

```
$ ls programs/_ppa/
__init__.py  canonical_json.py

$ ls programs/_ppa/backends
(does not exist)

$ ls schemas/ppa/
(does not exist)

$ python3 -m pytest programs/tests/test_ppa_canonical_json.py -q
8 passed
```

`canonical_json.py` is real, frozen, and has the eight tests the contract claims.
Everything else in §4 is a name in a document. `schemas/ppa/<name>.v1.schema.json`
(§5) has no directory yet, so the first lane to write a schema creates it.

---

## 5. What is red on `main` right now, and it is not a PPA thing

`gate_is_wired_check` **exits 1 on pristine `867de4289`**, in a clean worktree
with no lane's work in it:

```
$ python3 programs/gate_is_wired_check.py ; echo rc=$?
  gates: 608   unwired: 59 (baseline 59)   of those named in a skill: 28
  [NOTE] baseline shrank — now wired: analog_liberty_nonzero_delay_check.
  [FAIL] 1 gate(s) newly consulted by no automatic verdict:
     closed_loop_edge_check
rc=1
```

The *count* is balanced — 59 against a baseline of 59 — because one gate became
wired in the same window as one became unwired. A reader watching the number sees
nothing. The gate prints the NAME, and that is the only reason this is visible.

`closed_loop_edge_check` landed with no flow gate clause; its only non-comment
consumer is a file under `programs/tests/`, and `programs/tests/` is not a wiring
surface (`_EXECUTABLE_GLOBS` carries `programs/*.py`, which is not recursive).
That is the right doctrine — a gate reachable only from a test does not run on a
design — and it means the check that made `closed_loop` declarations falsifiable
is itself consulted by no automatic verdict.

---

## 6. What this file does NOT measure

Stated so a reader does not mistake silence for a clean result.

* **Whether a DECLARED_ONLY edge *should* be executable.** The census reports the
  state; which of the 18 deserve an actuator is a design decision with an owner,
  not a measurement.
* **The exit-code contract across all `ppa_*` programs.** `PPA_INTERFACES.md` §1
  records two shipped gates refusing with a bare `SystemExit`, which exits 1;
  this file did not sweep for more.
* **Anything about a specific design.** Every number here is a property of the
  flow document and of this repository's own source.
