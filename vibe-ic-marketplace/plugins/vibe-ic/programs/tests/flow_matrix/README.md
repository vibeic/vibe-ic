# `flow_matrix` — shared substrate for the flow-step × dimension coverage matrix

The Vibe-IC flow has **69<!--figure:flow_steps--> steps**. The 2026-07 audit
asked **9<!--figure:matrix_dimensions--> questions** of each one.
69<!--figure:flow_steps--> × 9<!--figure:matrix_dimensions--> =
**621<!--figure:ledger_cells--> cells**. This package is the substrate that
all eight dimension test-modules import so they agree on what a step is, what
a gate says, and which cells exist.

Five of those steps are PATH-SPECIFIC and do not run for every design: 0.5ic,
15.5ic, 26.5ic and 37.5ic belong to the chip/IC path, 37.5ip is the cell/IP
path's terminal step. They are cells here like any other — the matrix asks whether a
step is declared, wired and gated, not whether this design runs it. The
package name keeps its `63x8` spelling: it is the campaign's name, not a count.

Every digit in this file that describes the flow is DERIVED: it carries a
`<!--figure:...-->` anchor naming the binding that produced it, and
`tools/gen_flow_matrix_census.py --check` fails on drift. Repair with
`--fix-figures`; never hand-edit an anchored number. The same command
prints, on every verdict, how many figures it guards and how many stated
figures in this file it does NOT (vibe-ic#961).

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

Every one of the 621<!--figure:ledger_cells--> cells must end in **exactly
one** of these, all machine-checkable:

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
from flow_matrix import flowref as F

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
* **`blocks_on` is present on 69<!--figure:blocks_on_declared--> steps but non-empty on only 67<!--figure:blocks_on_nonempty-->.** D1 and A1
  declare it *empty* because they are the flow's genuine roots. "69<!--figure:blocks_on_declared--> steps have
  blocks_on" is a presence count, not a dependency count.
* **`total_steps: 44`** in the yaml counts the numeric steps only. It is not
  `len(steps)`.
* **Three exec-clause force levels**: `program_exit_zero` blocks,
  `advisory_program_exit_zero` does **not**, `optional_program_exit_zero`
  blocks only when its `condition_files_exist` are present. Treating an
  advisory clause as enforcement is measuring something adjacent.
* **No `program_exit_zero` form exists in `required_outputs`** — all 184<!--figure:required_output_entries-->
  entries are plain path strings. That form lives only in `gate`.

### `cells.py` — the 621<!--figure:ledger_cells-->-cell ledger
`ALL_CELLS` is the cross product of `flowref.step_ids()` × `DIMENSIONS`, built
**live from the yaml, never from the audit JSON**. Add or delete a step and the
ledger changes with the repo; `test_flow_matrix_ledger.py` notices.

`Cell.audit_verdict` / `Cell.audit_summary` are **history for humans**. Never
assert on them.

Audit source resolution: `$VIBE_IC_MATRIX_AUDIT_JSON` → `.audit_63x8.json`
walking up from the plugin root → the vendored `audit_history.json` if present.
If none resolves, every cell reads `ABSENT_FROM_AUDIT` and imports still
succeed — losing the history must never break a live predicate.

### `substitution.py` — what `ENFORCED` does not say
`ENFORCED` means a predicate ran and passed. It does not say WHAT it ran
against. Dimension 8 holds every step's gate at a known tier by substituting a
minimal stand-in for it — disclosed at length in its own docstring, and erased
the moment the census added eight rows together.

A dimension module may expose `matrix_cell_substitution(step_id)` beside
`matrix_cell_state`: `None` for "the step's own mechanism", a disclosure string
for "a stand-in, and here is which and why". A module that exposes nothing is
**UNDECLARED**, which is a third state and *not* a synonym for `None` —
reading silence as "not substituted" would republish the exact defect the
contract removes. Which dimensions have declared is pinned in
`test_flow_matrix_coverage.DIMENSIONS_DECLARING_SUBSTITUTION`, in both
directions, so a declaration cannot be dropped without the suite saying so.

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
file nobody reviewed. `test_flow_matrix_ledger.py` asserts the env var is
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
  python3 -m pytest programs/tests/test_flow_matrix_ledger.py -q
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
from flow_matrix import cells as C, flowref as F, waivers as W
```

`from programs.tests.flow_matrix.cells import ...` does **not**.

### The cell is a STEP; three dimensions naturally ask about a CLAUSE

The ledger's unit is a step, but dimensions 2 (falsifiability), 4
(criteria-match) and 6 (skip discipline) each ask their question of a gate
CLAUSE — 187<!--figure:blocking_clauses--> blocking clauses over 68<!--figure:gated_steps--> gated steps. A cell-level
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

## The census

Reported by `programs/tests/test_flow_matrix_coverage.py`, which collects the
eight modules through pytest's own machinery, asks each module the state of the
cells it owns, and then RUNS those modules and joins the answer against what
each cell's predicate actually did. **621<!--figure:ledger_cells--> / 621<!--figure:ledger_cells--> cells present,
exactly once.**

**The census has TWO axes, and the first is not quotable on its own.** A cell's
STATE says how it is configured; its OUTCOME says what its predicate did on
this tree, this minute. Until 2026-08-09 only the state was ever reported, and
the two had drifted: the published table read `ENFORCED 483` while the live
state census read 481 **and 26 of those 481 cells were failing** — a cell whose
own predicate is red was being counted as proof of enforcement
(ORGANIC-20260808). `ENFORCED-CONTRADICTED` is that gap, made visible; it is
not a fourth state but a *disagreement* between the two axes, and
`test_no_cell_is_counted_enforced_while_its_predicate_is_red` fails while any
cell is in it because its predicate RAN and said so.

**AND IT REFUSES, RATHER THAN FAILS, WHEN NOTHING WAS MEASURED** (owner
ruling 2026-08-28). A cell that disagrees because its predicate never returned
a verdict — the `-SKIPPED` labels, which the NOT MEASURED column of the
generated block below already counts as exactly that — has produced no finding
about this tree. `benchmark-data` was moved out of this repository and large
raw geometry is not committed, both by design, so reddening on their absence
measures the policy and reports it as a defect. When the MEASURED RED class is
empty and the NOT MEASURED class is not, that test now SKIPS carrying the same
enumeration: a gate that could not run has not passed, and it has not failed
either. ONE measured red still fails it.

The per-dimension numbers for BOTH axes live in the generated block below;
this section deliberately quotes none of them, because a hand-copied total is
exactly what #889 removed.

The table below is **GENERATED** by `tools/gen_flow_matrix_census.py` and
diffed against the tree by `programs/tests/test_flow_matrix_census_freshness.py`.
It was hand-written until 2026-08-09, and by then it had drifted: it published
`483 / 9 / 12` while the reproduce command printed underneath it returned
`481 / 11 / 12`, with four of the eight rows wrong. A number nobody recomputes
rots at exactly the rate the tree moves, and every cell under this total was
already being recomputed live — so the total is now recomputed too.

The ENFORCED column is printed SPLIT and there is deliberately no single
"enforcing" figure. Dimension 8 substitutes a stand-in gate for most of its
cells, says so at length in its own docstring, and that disclosure used to die
the moment eight rows were added up. See `substitution.py`.

<!-- BEGIN GENERATED CENSUS — tools/gen_flow_matrix_census.py — DO NOT EDIT BY HAND -->

**621 cells: 541 ENFORCED, 0 ENFORCED-CONTRADICTED, 7 WAIVED, 17 NA, 10 NOT_MEASURED, 44 ENFORCED-SKIPPED, 2 WAIVED-SKIPPED.**

The 0 CONTRADICTED cells are configured as enforcing while their own predicate is currently RED. They are NOT folded into the 541: a cell whose predicate fails is not evidence of enforcement. See vibe-ic#888.

Corpus at generation: NOT_OFFERED — no published cell was read. Every figure below is a function of this commit alone.

**What these 621 cells measure — and what they do not.** Every cell asks whether a step is declared, wired, and reached by a gate. NO cell reads the CONTENT of the artefact a step produces. A shipped sign-off artefact can violate the very criterion its step is named after and no cell here changes colour. Read this table as COVERAGE SHAPE, never as evidence that a design is correct.

`ENFORCED` is published SPLIT, because it is not one thing. It means a live predicate ran and passed; it does not say WHAT it ran against, and that turns out to be three different answers:

* **10** — measured against the step's OWN mechanism. This is the only figure that means what "enforcing" sounds like, and it is a floor: the two rows below are not evidence against it, they are the part nobody has evidence for.
* **126** — measured against a SUBSTITUTED stand-in. The predicate runs and passes; what it exercises is not the mechanism the cell is named after. Each one carries a disclosure from the module that owns it.
* **405** — in dimensions that have not answered the question at all. NOT counted as clean: UNDECLARED is a state, not a synonym for "own mechanism". See `substitution.py`, "WHY UNDECLARED IS A STATE AND NOT A DEFAULT".

The 7 WAIVED and 17 NA cells are not enforcing anything and enter none of those columns. There is deliberately no single "enforcing" total to quote.

| dim | question | ENFORCED: own | ENFORCED: substituted | ENFORCED: undeclared | CONTRADICTED | NOT MEASURED | WAIVED | NA |
|-----|----------|--------------:|----------------------:|---------------------:|-------------:|-------------:|-------:|---:|
| 1 | `wiring` — Is the gate actually wired — does something real parse and execute it? | 0 | 0 | 69 | 0 | 0 | 0 | 0 |
| 2 | `falsifiable` — Can the gate fail? Is there a reachable non-zero-exit branch? | 0 | 0 | 66 | 0 | 0 | 2 | 1 |
| 3 | `outputs_produced` — Are the declared required_outputs genuinely produced? | 0 | 0 | 0 | 0 | 56 | 0 | 13 |
| 4 | `criteria_match` — Does the gate measure what its name and docstring claim it measures? | 0 | 0 | 69 | 0 | 0 | 0 | 0 |
| 5 | `deps_correct` — Is blocks_on the true upstream set — no missing and no phantom edge? | 0 | 0 | 68 | 0 | 0 | 1 | 0 |
| 6 | `skip_discipline` — Is every skip / vacuous-pass disclosed rather than counted as a pass? | 0 | 0 | 69 | 0 | 0 | 0 | 0 |
| 7 | `outputs_list_complete` — Is required_outputs complete — does the step emit artefacts it never declares? | 0 | 0 | 64 | 0 | 0 | 4 | 1 |
| 8 | `missing_caught` — When a declared output IS missing, which mechanism catches it? | 9 | 58 | 0 | 0 | 0 | 0 | 2 |
| 9 | `verdict_consumed` — When this step FAILs, does the verdict reach the exit code — or is it reported and discarded? | 1 | 68 | 0 | 0 | 0 | 0 | 0 |
| **total** | | **10** | **126** | **405** | **0** | **56** | **7** | **17** |

**NOT MEASURED is not a pass and not a defect.** Those 56 cells have a predicate that declined to run, naming a resource it could not reach — most often a published corpus this checkout does not carry. They are counted here so a dimension whose cells could not be driven cannot read as a dimension with nothing to report; read them as UNKNOWN, never as coverage.

Regenerate (never edit this block by hand, and never quote it without re-running):

```
python3 tools/gen_flow_matrix_census.py          # rewrite
python3 tools/gen_flow_matrix_census.py --check  # exit 1 on drift
```

<!-- END GENERATED CENSUS -->

> **Dimension 6 went back UP, because the defect it was measuring was
> fixed.** 59/4/0 -> 62/1/0. Leg L3c measures whether a step on the
> VACUOUS_PASS tier is still inside the published `X/Y executed PASS`
> numerator — a skip counted as a measurement in the number a reviewer reads.
> It charged four cells: 14, 30, FS1 (waived, against one pending owner
> decision) and step 4, which was waived NOWHERE and is the cell that turned
> `main` red on hosts where its gate lands on the tier rather than on FAIL.
>
> The owner ruled: VACUOUS_PASS leaves the numerator.
> `flow_compliance_check` now computes `pass_count = counts["PASS"]`. The tier
> keeps its own label and its own counter, does NOT become a failure, and does
> NOT leave the denominator — a gate that ran and found nothing to audit is an
> unmet requirement, unlike SKIPPED-CONDITION (the step's own condition was
> evaluated and not met), which is subtracted. Every rendering of the
> numerator moved together: the checker headline, which now also names the
> excluded vacuous count in the same parenthesis, plus
> `final_report_generate`'s `_counts_snapshot`, its prose bullet, its
> stage-breakdown PASS column and its resource log. All three are now
> compared against each other on one audit run by
> `test_report_executed_pass_equals_the_checkers_own_headline`; before
> 2026-07-28 the stage column was the third rendering and nothing compared it,
> so reverting it alone was caught by nothing.
>
> The escape hatch this rationale leans on is NARROWER than the sentence
> above suggests, and the scope is measured rather than implied. An honestly
> inapplicable step is SKIPPED-CONDITION and leaves Y — but only a step that
> DECLARES a step-level `condition` can ever reach that tier, and on the
> canonical flow that is 22 of 63 (all of A1-A9, M1-M4, DT*, FS*). For the
> other 41 — D1, 1-39, P0 — an inapplicable input lands on VACUOUS_PASS and
> IS a permanent Y-debit, exactly the cost the withdrawn waivers named. It is
> narrowed, not eliminated; closing it for a given step means giving that
> step a condition, which is a flow change, not a numerator change.
>
> All three L3c waivers are REMOVED, not re-worded — `strict=True` would turn
> them into XPASS failures. DT2 stays waived, for leg L4, unrelated to this.
> Leg L3c stays armed and now charges 0 of 63; `test_d6_l3c_fires_when_the_
> numerator_folds_the_tier_back_in` restores the old arithmetic in a copy of
> the checker and shows the leg catching it, so a silent leg is not mistaken
> for a clean tree.
>
> MEASURED cost, on this host, over all 12 tracked run roots of
> `programs/tests/fixtures/matrix_d3_output_manifest.json`, each COPIED and
> re-run with the shipped checker, full flow, `--strict`: 12/12 roots move
> their published numerator, 37 step-instances leave X, 0 of 756 per-step
> verdicts change, 0 of 12 Overall verdicts change (all 12 were FAIL before
> and after). #01 4/7->3/7, #02 3/39->2/39, #03 11/26->6/26, #04 18/39->13/39,
> #05 7/53->4/53, #06 14/30->11/30, #07 20/42->16/42, #08 19/32->16/32,
> #09 15/53->11/53, #10 5/10->4/10, #11 7/41->4/41, #12 31/42->27/42.
> That no verdict moves is structural, not a property of this corpus:
> `pass_count` is assigned once and read once, in the headline `print`, and
> feeds none of `failing` / `missing` / `setup_required_skipped` /
> `oss_blocked_skipped` / `ok`.
> A lower honest number beats a higher fake one; that is the whole point of
> this suite.
>
> **The commit that shipped this also carried the dimension-7 declaration on
> step 27**, so the AS-SHIPPED sweep over the same 12 roots reads: 12/12
> headlines move, **40** step-instances leave X (37 vacuous + 3 from step 27),
> **3 of 756** per-step verdicts change and **0 of 12** Overall verdicts
> change. The three are all step 27, on the three roots carrying a crosstalk
> report and no MCF report: #03 PASS -> DEFERRED-BY-UPSTREAM (a cascade, which
> is also why its denominator moves 26 -> 25), #04 and #09 PASS -> MISSING.
> Combined headlines for those three: #03 11/26->5/25, #04 18/39->12/39,
> #09 15/53->10/53.
>
> That measurement DISAGREES with the one the withdrawn waivers carried
> ("35 step-instances", and five different before-headlines). Re-measured
> here step by step: the earlier count omitted step 27, vacuous on 2 of the 12
> roots. Per-step instance counts otherwise agree exactly — D1 11/12,
> FS1 10/12, 14 7/12, 24 3/12, 4 2/12, 30 1/12, 31 1/12, plus 27 2/12 = 37.
> The before-headline differences (#06, #07, #08, #10, #12) are host state:
> several gates change tier with local tool availability, which is also why
> step 4 was clean on the host that removed its waiver and red here.

> **Dimension 3 did not move**, and that is the reconciled answer to a
> convergence pass that reported 53/1/9. Both of its retirements were measured
> and reverted:
>
> **CORRECTION, measured 2026-08-09 on `dee025059`** — this block is a record
> of a decision taken then, left standing as such, but it no longer describes
> the tree: the live census reports **A8/d3 as ENFORCED, not WAIVED**, and
> `flow_matrix.waivers.WAIVERS` carries no entry for it (which is why
> `test_state_agrees_with_the_waiver_registry_and_the_collected_marks` is
> green). The waiver was retired by a later change than this note; who and why
> is not re-derived here rather than guessed at. Dimension 3 now reads
> ENFORCED 34 / ENFORCED-CONTRADICTED 19 / WAIVED 3 / NA 7. Do not read the
> paragraphs below as a statement about the current tree.
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
> ORIGINAL defective `programs/postroute_timing_repair_audit.py` — in which
> `grep -c postroute_timing_repair_decision` is 0 — left the cell green. That channel is
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

* dimension 8's ENFORCED cells mostly run against a **substituted** gate; only
  the steps in `REAL_GATE_PASS_TIER_STEPS` are measured with the step's own
  gate. This one is no longer a caveat you have to remember while reading the
  total — it is a column in the generated table above, produced by
  `matrix_cell_substitution()` on the module that owns those cells, so a
  reader who quotes the census gets the split whether or not they read this
  bullet. That is what the other two below still lack;
* dimension 3's seven `EXTERNALLY_ATTESTED_STEPS` fall back to a committed
  manifest on any host without the campaign's out-of-repo run trees;
* dimension 6's legs L1 and L2 are structurally inert for most steps; L1b and
  L3/L3b carry the dimension, and
  `test_d6_every_cell_has_at_least_one_capable_leg` is what keeps that honest.

### Can a cell be reddened by changing a number in a PUBLISHED REPORT?

**8<!--figure:artefact_mutations_registered--> artefact mutations registered;
1<!--figure:artefact_cannot_redden--> currently prove the cell they target
cannot redden.**

Both digits are ANCHORED and re-derived by
`tools/gen_flow_matrix_census.py --check-figures` against
`matrix_mutation_ledger` itself. They were hand-typed until 2026-08-12 and by
then the first was right and the second was wrong by three: the ledger's own
count moved 4 -> 2 -> 1 across `46dbf43d` and `fc664a57`, each time in the
change that closed the gap it measured, and this file went on publishing 4 with
a four-row table naming three gates as unable to fail that had learned to fail.
The replay guards the LEDGER; nothing guarded its PUBLICATION. A stale "this
gate cannot fail" is the worse direction of that error — it reads as a disclosed
known gap, so it collects the credit for honesty while describing a gate that is
now doing its job.

That is the `ARTEFACT_MUTATION` channel of `programs/matrix_mutation_ledger.py`,
added because the ledger's first two channels both edit the SOURCE — the flow
yaml and the plugin tree — and neither could express the question. "No cell reads
artefact CONTENT" (finding #20) was never a policy: it was a consequence of there
being no way to say such a thing.

Each entry names a published run under `benchmark-data/`, a file in it, an exact
byte edit, the cell `(step, dim)` it bears on, and the verdict that was MEASURED;
the replay copies the run for real, applies the edit, and re-runs that step's own
gate through the flow's own verdict mapping. Run it with
`matrix_mutation_ledger.py --replay-artefacts` (3.1 s for all 8) and read the
count with `--census`.

The ones that prove a cell CANNOT redden are the point of the channel, not its
residue. The table below is the LIVE finding set and every cell named in it must
be one `matrix_mutation_ledger.artefact_findings()` currently returns —
`test_matrix_artefact_mutation_channel.test_the_readme_publishes_the_live_finding_set`
compares the two in BOTH directions, so a finding that closes cannot be left
standing here and a finding that opens cannot be left unpublished.

<!-- ARTEFACT FINDINGS TABLE — the `cell` column must equal
     matrix_mutation_ledger.artefact_findings(); do not edit by hand without
     re-running --replay-artefacts -->

| cell | edit | what the gate did |
|---|---|---|
| 33/d2 | every non-zero power figure x1000 | PASS — tool signature and categories are checked; the numbers are read against nothing |

<!-- END ARTEFACT FINDINGS TABLE -->

**Three entries left this table by being FIXED, and what they were is worth
keeping.** `ART-EM-CURRENT-DENSITY` (25/d2, peak power-grid segment current
1.96e-04 A → 5.0 A) passed because no Jmax was resolved, so no current was
refusable; it reddens now that a peak current has a declared authority to be
compared against. `ART-NETLIST-PRIMITIVE-SWAP` (9/d2, 221 `$_NAND_` → `$_AND_`)
and `ART-ROUTER-FINAL-ITERATION` (21/d2, the router's FINAL iteration
`DRT-0199` 0 → 12) both passed because the gate believed a summary the RUNNER
wrote instead of the output the TOOL wrote — step 21 kept printing
`real_violation_total=0` while the same gate on the same file *did* redden when
the runner's summary was edited 0 → 17. Its green was a statement about the
runner's arithmetic, not the router's result. That is the shape to look for
next, and it is the reason these three are recorded here rather than deleted.

The remaining entry is not open work in the same sense as the three that closed:
the ledger's own note records that step 33's cell REFUSES, naming the budget it
lacks, and no published run declares the budget that would let it redden. A cell
that refuses is not a cell that passes.

These are pinned by `ARTEFACT_CANNOT_REDDEN_AS_MEASURED`, and pinned is not
waived — the day a gate learns to read its artefact, its replay stops matching
the record and the gate file fails by name, demanding the entry be updated in the
same change that closes the gap. Closing them is separate work and is
deliberately not done by the channel that measures them.
