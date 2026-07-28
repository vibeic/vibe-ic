# `matrix_63x8` — shared substrate for the 63 × 8 coverage matrix

The Vibe-IC flow has **63 steps**. The 2026-07 audit asked **8 questions** of
each one. 63 × 8 = **504 cells**. This package is the substrate that all eight
dimension test-modules import so they agree on what a step is, what a gate
says, and which cells exist.

It contains no predicates of its own. It enumerates, it resolves, it carries
history. Deciding whether a cell is healthy is the dimension modules' job.

---

## The one rule

This whole campaign exists because of gates that **measured something adjacent
to the question and reported it as if it answered the question**. Do not
reproduce that disease in the tests built on this substrate.

Four specific forms of it, all of which an adversarial verifier will catch:

1. **Asserting the stored audit verdict.** `.audit_63x8.json` is used only to
   (a) enumerate history and (b) give a human context. `cell.audit_verdict` is
   a fact about a JSON file, not about the repository. Every predicate must be
   **recomputed live from the current source tree**.
2. **A predicate that cannot fail.** Before keeping a test, mutate the thing it
   guards and prove it goes red. If no mutation reddens it, the test is
   worthless — say so and record the cell as an honest gap.
3. **Substring / static scans over dynamic dispatch.** This codebase dispatches
   via `__import__(f"{name}_protocol_synth")`, glob + importlib, and
   `spec_from_file_location`. PR #460 shipped a broken change *because* a grep
   could not see this, and its own commit message documented the lesson one
   screen before violating it. If you scan source text: strip comments and
   strings **first** (a `# e.g. "foo_check"` comment was once counted as a call
   site), and resolve f-string / dynamic forms explicitly.
4. **Silent absence.** A cell with no test is not covered.

---

## The three-state rule

Every one of the 504 cells must end in **exactly one** of these, all
machine-checkable:

### `ENFORCED`
A live predicate runs and passes. The predicate reads the current source tree
(yaml, program source, program behaviour) — never a stored verdict.

```python
def test_step_gate_is_wired(...):
    assert F.gate_programs(step_id), f"{step_id}: gate names no resolvable program"
```

### `WAIVED`
```python
@pytest.mark.xfail(strict=True, reason=waiver.xfail_reason)
```
`strict=True` is **required**. It is the entire anti-rot mechanism: when the
underlying gap gets fixed and the predicate starts passing, the suite goes red
on XPASS and forces the waiver's removal. A non-strict `xfail` rots silently
forever — silent absence in a different costume.

A waiver needs a `reason` that says *what a program cannot decide and why*, and
`evidence` that is independently verifiable (a `path:line`, a measured value
with the command that produced it, or a decision reference). "not implemented
yet" is not a reason; `waivers.validate()` rejects it.

### `NA`
The test asserts **the NA precondition still holds**.

```python
def test_stepFS1_declares_no_required_outputs():
    # NA for dimension 3: there is nothing to produce.
    assert not F.declares_required_outputs("FS1")
```

If someone later adds `required_outputs` to FS1, the NA self-invalidates and
the test fails, forcing re-evaluation. **An NA that just `pytest.skip()`s
unconditionally is forbidden** — that is silent absence wearing a hat.

---

## The eight dimensions

| # | name | the question |
|---|------|--------------|
| 1 | `wiring` | Is the gate actually wired — does something real parse and execute it? |
| 2 | `falsifiable` | Can the gate fail? Is there a reachable non-zero-exit branch? |
| 3 | `outputs_produced` | Are the declared `required_outputs` genuinely produced? |
| 4 | `criteria_match` | Does the gate measure what its name and docstring claim? |
| 5 | `deps_correct` | Is `blocks_on` the true upstream set — no missing, no phantom edge? |
| 6 | `skip_discipline` | Is every skip / vacuous-pass disclosed rather than counted as a pass? |
| 7 | `outputs_list_complete` | Is `required_outputs` complete — does the step emit artefacts it never declares? |
| 8 | `missing_caught` | When a declared output IS missing, which mechanism catches it? |

Dimensions **1–7 ask about the GATE**. Dimension **8 asks about the CATCHER**,
which is a different *kind* of question, so it sits last and the number equals
display order. **The audit JSON is already in this numbering.** There is no
legacy mapping to apply and none must be introduced — a maintained old/new
cross-reference is exactly the maintenance burden this renumbering removes.

---

## Modules

### `flowref.py` — live accessors over the flow yaml
Everything recomputed from `flow/phase1_phase2_phase3.yaml` and memoised with
`functools.lru_cache`. Read its module docstring before writing a predicate: it
records **the grammar as measured**, including the places where the grammar in
circulation is wrong.

```python
from matrix_63x8 import flowref as F

F.step_ids()                    # 63, raw MIXED types: 'D1', 1, 'FS1', 44 …
F.step_by_id(12) is F.step_by_id("12")
F.gate_clauses(sid)             # typed GateClause tuple, force levels included
F.gate_programs(sid)            # basenames that resolve to programs/<n>.py
F.unresolved_gate_programs(sid) # basenames that do NOT — a live wiring defect
F.required_outputs(sid)         # raw, unsplit entries
F.classify_output(entry)        # FILE | GLOB | ANY_OF | PROGRAM_EXIT
F.split_any_of(entry)           # exactly what flow_compliance_check does
F.blocks_on(sid)                # raw, mixed types
F.declares_blocks_on(sid)       # KEY present, even if the list is empty
```

Things that will bite you if you skip the docstring:

* **Step ids are mixed `str`/`int`.** Never assume int; never sort naively.
* **`required_outputs` is ALL-of across entries**, but `" OR "` *inside* one
  entry is any-of. It used to be any-of across entries and that was a real
  false-pass bug — see `programs/flow_compliance_check.py` ~line 6150.
* **`blocks_on` is present on 62 steps but non-empty on only 60.** D1 and A1
  declare it *empty* because they are the flow's genuine roots. "62 steps have
  blocks_on" is a presence count, not a dependency count.
* **`total_steps: 44`** in the yaml counts the numeric steps only. It is not
  `len(steps)`.
* **Three exec-clause force levels**: `program_exit_zero` blocks,
  `advisory_program_exit_zero` does **not**, `optional_program_exit_zero`
  blocks only when its `condition_files_exist` are present. Treating an
  advisory clause as enforcement is measuring something adjacent.
* **No `program_exit_zero` form exists in `required_outputs`** — all 126
  entries are plain path strings. That form lives only in `gate`.

### `cells.py` — the 504-cell ledger
`ALL_CELLS` is the cross product of `flowref.step_ids()` × `DIMENSIONS`, built
**live from the yaml, never from the audit JSON**. Add or delete a step and the
ledger changes with the repo; `test_matrix_63x8_ledger.py` notices.

`Cell.audit_verdict` / `Cell.audit_summary` are **history for humans**. Never
assert on them.

Audit source resolution: `$VIBE_IC_MATRIX_AUDIT_JSON` → `.audit_63x8.json`
walking up from the plugin root → the vendored `audit_history.json` if present.
If none resolves, every cell reads `ABSENT_FROM_AUDIT` and imports still
succeed — losing the history must never break a live predicate.

### `waivers.py` — the accepted-gap registry
`WAIVERS` **starts empty**. The eight dimension modules share one worktree, so
a sibling that needs a waiver **reports it to the orchestrator** rather than
editing this file; concurrent edits to a shared registry lose entries.

---

## Proving falsifiability

`flowref.set_flow_yaml(path)` + `cells.rebuild()` repoint the substrate at a
mutated scratch copy so a predicate can be reddened without touching the real
yaml (eight agents share this worktree — **never edit it in place**).
`$VIBE_IC_MATRIX_FLOW_YAML` does the same at import time.

Both are loaded guns: a suite run with the override set grades itself against a
file nobody reviewed. `test_matrix_63x8_ledger.py` asserts the env var is
**unset**, so a normal run cannot be silently redirected.

The substrate's own predicates were mutation-proved: **16/16 mutations reddened
the suite at the intended assertion** — ledger sourced from the audit instead
of the yaml; `" OR "` split degraded to `"OR"`; `program_path` dropping its
existence check; `blocks_on()` reporting key presence instead of list contents;
advisory clauses reported as blocking; the gate walker dropping
`optional_program_exit_zero`; dimension-8 prose guessed into `OK`/`NA` by
grepping for "N/A"; step ids stringified at build time; missing history reading
`OK` instead of `ABSENT_FROM_AUDIT`; the waiver validator accepting a
placeholder or dropping the evidence requirement; `xfail_mark` losing
`strict=True`.

## Running

```bash
cd .../plugins/vibe-ic && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python3 -m pytest programs/tests/test_matrix_63x8_ledger.py -q
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` is mandatory here: a stray `pytest_ethereum`
plugin otherwise breaks collection.

## Notes the dimension agents asked to record centrally (2026-07-27)

These are not rules; they are measured facts that more than one dimension
rediscovered independently, written down once so the ninth agent does not
rediscover them a ninth time.

### The import path that works

Under the plugin's `pytest.ini` (`--import-mode=importlib`) plus the root
`conftest.py`, only this spelling resolves:

```python
from matrix_63x8 import cells as C, flowref as F, waivers as W
```

`from programs.tests.matrix_63x8.cells import ...` does **not**.

### The cell is a STEP; three dimensions naturally ask about a CLAUSE

The ledger's unit is a step, but dimensions 2 (falsifiability), 4
(criteria-match) and 6 (skip discipline) each ask their question of a gate
CLAUSE — 150 blocking clauses over 62 gated steps. A cell-level
`xfail(strict=True)` cannot express "5 of this step's 6 clauses are proven and
the 6th is not", so those modules carry an in-module per-clause register with
the same both-directions anti-rot semantics (a stale entry reddens; an entry
that starts passing reddens). A green cell in those dimensions therefore means
"every blocking clause proven except the ones this module names", not "the
whole step is proven".

### The CRASH / TIMEOUT trap for anything that shells out

`flow_compliance_check._check_program_exit_zero` returns `passed=False` for an
unhandled Python traceback and for a killed subprocess exactly as it does for a
real FAIL verdict. Measured while building dimension 2: `rtl_hygiene_lint` and
`rom_init_lint` exit 1 with a `FileNotFoundError` when `reports/phase2/lint/`
does not exist, which would have certified them falsifiable without the linter
ever running. Any sibling that reads `passed` must:

* strip tracebacks and `TIMED OUT` **before** the FAIL branch, and
* pre-create the gate's own `--json` parent directory.

And the string it hands you is `(stdout[-300:] + "\n" + stderr[-300:]).strip()`
— **truncated**. One frame line in this tree is ~85-120 characters, so any
traceback deeper than two frames arrives without its
`Traceback (most recent call last)` header. Matching on that header alone
grades a crashing gate as a working one; match on a frame line
(`^\s*File "...", line N, in <name>`) as well. This was a live HIGH finding
against dimension 2 on 2026-07-27, not a hypothetical.

### `flow_compliance_check` module attributes are rebindable, and two modules do it

`test_matrix_d1_wiring.py` temporarily rebinds `_check_program_exit_zero`,
`_check_files_exist`, `_check_json_field_true` and `subprocess` on the
compliance module inside `try/finally`, once per gated step, to record what the
REAL walker dispatches. Restoration is asserted. This is safe under
single-threaded pytest but would **not** be safe under
`pytest-xdist --dist loadfile` sharing a process, or if the suite ever gains
thread-parallel test execution.

## The census, as it stands after the 2026-07-28 convergence merge

Reported by `programs/tests/test_matrix_63x8_coverage.py`, which collects the
eight modules through pytest's own machinery and asks each module the state of
the cells it owns. **504 / 504 cells present, exactly once.**

| dim | question                | ENFORCED | WAIVED | NA |
|-----|-------------------------|---------:|-------:|---:|
| 1   | wiring                  | 63       | 0      | 0  |
| 2   | runnable / falsifiable  | 62       | 0      | 1  |
| 3   | outputs produced        | 52       | 4      | 7  |
| 4   | criteria match          | 63       | 0      | 0  |
| 5   | deps correct            | 62       | 0      | 1  |
| 6   | skip discipline         | 59       | 4      | 0  |
| 7   | outputs list complete   | 58       | 4      | 1  |
| 8   | missing mechanism       | 61       | 0      | 2  |
| **total** |                   | **480**  | **12** | **12** |

Reproduce (never quote this table without re-running it):

```
cd vibe-ic-marketplace/plugins/vibe-ic && PYTHONPATH=.:programs:programs/tests \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -c \
  "import sys; sys.path[:0]=['programs','programs/tests']; \
   import test_matrix_63x8_coverage as CV, collections; \
   print(collections.Counter(CV.state_census().values()))"
-> Counter({'ENFORCED': 480, 'NA': 12, 'WAIVED': 12})
```

> **Dimension 6 went DOWN, on purpose.** 60/3/0 -> 59/4/0. Step 14 was
> ENFORCED and is now waived because a new leg — L3c — measures something the
> dimension previously only described in prose: a step on the VACUOUS_PASS
> tier is still inside the published `X/Y executed PASS` numerator, so a skip
> is counted as a measurement in the number a reviewer reads. Step 30 is
> charged by the same leg; its earlier LABEL-half waiver had been closed by
> #521 and it re-enters the registry for the ARITHMETIC half only. DT2 is
> waived again after its closure was measured to be a regression (below). A
> lower honest number beats a higher fake one; that is the whole point of this
> suite.
>
> A convergence pass also proposed waiving step 4 on the same leg. Re-measured,
> step 4's SEEDED probe resolves to FAIL — its gate now runs
> `verilator_coverage_measure check`, which classifies a seeded coverage
> artefact as another producer's payload — so L3c has nothing to charge there
> and the strict xfail XPASSed. The waiver was not carried.

> **Dimension 3 did not move**, and that is the reconciled answer to a
> convergence pass that reported 53/1/9. Both of its retirements were measured
> and reverted:
>
> * **A8** stays WAIVED, with the reason NARROWED. Its `.gds` really did have
>   no producer — `magic_port_extract_emit.build_gds_write_tcl` had shipped
>   since v0.1.114 with a unit test and no caller — and
>   `programs/analog_hardmacro_gds_emit.py` is now that producer, declared in
>   A8's `programs:` and dispatched by `analog_one_shot_runner`, deliberately
>   NOT by A8's gate (`flow_compliance_check` is the acceptance auditor and
>   must not create what it certifies). What is still out of reach is the
>   EVIDENCE: Magic streams the layout inside the EDA container, the
>   producer's documented rc=2 names the gap, and neither CI — a plain runner
>   with pytest and no docker — nor a fresh clone has that container. Marking
>   the entry `PRODUCED_LIVE` makes the cell green where a container runs and
>   red everywhere else, which is the host-dependence #527 removed from this
>   module.
> * **6** and **39** stay WAIVED. The proposal reclassified them
>   `NA_TOOLCHAIN_ABSENT` on a live assertion that Intel Quartus "is reachable
>   from nowhere this suite can run". Re-measured on the maintainer host, the
>   flow's own locator returns an executable `quartus_sh` under an external
>   mount, so the NA's own self-invalidating assertion fires and both cells go
>   red. The NA's design was sound; its premise was a property of one machine.
>   The waivers' premises are properties of the COMMIT (`git ls-tree -r HEAD`
>   matches no tracked `.sof` or `.map.rpt` anywhere) and are re-executed every
>   run.
> * **M1** stays WAIVED with a narrower, re-measured reason: the merge producer
>   ships and is wired; no admissible run root carries both a digital sign-off
>   GDS and an analog hardmacro GDS, which is the input set it needs.

> The dimension-5 row moved 5 -> 0 WAIVED on 2026-07-28: all five of that
> dimension's waivers said "LIVE DEFECT, reproduced" and all five were
> closed by fixing the defect (two declared edges, one broken A5/A6 cycle,
> one gate moved off a step that could not declare what it read, one yaml
> block moved to kill the flow's only forward edge). Breaking the A5/A6 cycle
> DID drop a defect class on its own — A5 read the PV flags, A6 prefers the
> PV report, so a project whose flag contradicts its report went from rc 1 to
> rc 0 at both gates — and that is closed separately by
> `analog_a6_block_pv_check._witness_disagreements`, measured in both
> directions and on all 23 tracked analog run roots.

> **Dimension 4 closed all ten**, and one of them nearly closed on the wrong
> evidence: step 32's cell passed on the flow yaml alone, because
> `condition_files_exist` was accepted as artefact GROUNDING. Restoring the
> ORIGINAL defective `programs/eco_loop_audit.py` — in which
> `grep -c eco_trigger_decision` is 0 — left the cell green. That channel is
> withdrawn (`matrix_d4_probe.gate_declared_paths`); the cell now reddens on
> its own defect and passes on the fix.

> **Dimension 6's DT2 cell is waived again.** Its closure re-armed DT2's
> condition on the producer's own outputs. Measured on a real tracked run
> root with one mutation — delete the at-speed grade, the artefact DT2 exists
> to report on — that turns MISSING/rc 1 into SKIPPED-CONDITION/rc 0 and drops
> the step out of the executed-PASS denominator. The condition is back to the
> declared ALL-of, the hole is back in
> `flow/flow_condition_reachability_baseline.json`, and the waiver names the
> single thing that closes it: a flow-level non-fatal "ran, disclosed, could
> not measure" verdict that COSTS the denominator.

`ENFORCED` means the cell's live predicate runs and passes. It does **not** mean
the predicate is strong enough to catch every defect of that kind — read the
owning module's `KNOWN GAP` section before quoting any of these numbers. Three
that matter most:

* dimension 8's 61 ENFORCED cells run against a **substituted** gate; only the
  14 steps in `REAL_GATE_PASS_TIER_STEPS` are measured with the step's own gate;
* dimension 3's seven `EXTERNALLY_ATTESTED_STEPS` fall back to a committed
  manifest on any host without the campaign's out-of-repo run trees;
* dimension 6's legs L1 and L2 are structurally inert for most steps; L1b and
  L3/L3b carry the dimension, and
  `test_d6_every_cell_has_at_least_one_capable_leg` is what keeps that honest.
