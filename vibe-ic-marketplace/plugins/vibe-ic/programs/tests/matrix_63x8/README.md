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

## The census, as it stands after the 2026-07-27 close-out

Reported by `programs/tests/test_matrix_63x8_coverage.py`, which collects the
eight modules through pytest's own machinery and asks each module the state of
the cells it owns. **504 / 504 cells present, exactly once.**

| dim | question                | ENFORCED | WAIVED | NA |
|-----|-------------------------|---------:|-------:|---:|
| 1   | wiring                  | 63       | 0      | 0  |
| 2   | runnable / falsifiable  | 62       | 0      | 1  |
| 3   | outputs produced        | 52       | 4      | 7  |
| 4   | criteria match          | 53       | 10     | 0  |
| 5   | deps correct            | 57       | 5      | 1  |
| 6   | skip discipline         | 60       | 3      | 0  |
| 7   | outputs list complete   | 53       | 9      | 1  |
| 8   | missing mechanism       | 61       | 0      | 2  |
| **total** |                   | **461**  | **31** | **12** |

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
