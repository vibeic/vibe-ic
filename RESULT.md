<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
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

=======
# The 63x8 matrix family on main: 54 red test IDs, driven to 12

Branch `jmatrix/63x8-main-reds`, six commits, now rebased onto `origin/main`
`e36d81c0a` (v1.11.33). The 54 were measured at `867de4289` (v1.11.18) and are
re-measured here on both bases.

**42 of the 54 are green. 12 remain, and they now form one dependency graph
rather than a list.**

## Base: rebased onto v1.11.33. NEITHER BRANCH HAS LANDED.

I was told main was v1.11.47 with `jmatrix/63x8-main-reds` landed as v1.11.44 and
`jfindings/63x8-producer-identity` as v1.11.39. **None of that is true of the
remote.** Checked four independent ways before saying so:

```
$ git show origin/main:.../plugin.json | grep version
  "version": "1.11.33",
$ git log --all --oneline --grep="v1\.11\.3[4-9]\|v1\.11\.4[0-9]" | wc -l
0
$ git merge-base --is-ancestor <each branch head> origin/main
  jmatrix/63x8-main-reds            NOT on main
  jfindings/63x8-producer-identity  NOT on main
$ git grep -c CONTENT_ARM_UNGRADABLE_SELF_WRITTEN origin/main   -> 0
$ git grep -c CROSSLAYER_SEARCH_UNDECLARED        origin/main   -> 0
$ git grep -c _measured_subject                   origin/main   -> 0
```

The last check is the one that matters, because a landing rewrites SHAs: searched
by CONTENT, not commit id, none of this work is on main. v1.11.34 and above do
not exist on this remote.

Main HAS moved, by 16 commits — `867de4289` (v1.11.18) to `e36d81c0a`
(v1.11.33), the fourteen PPA lanes plus a PREPARE and an ACTIVATE. So the
re-measurement was still worth doing, and this branch is now rebased onto it.
The rebase was clean; main touched one file this branch touches
(`test_matrix_d2_falsifiable.py`, at `e36d81c0a`) and every change survived.
The matrix population is **69** under v1.11.33, unchanged.

### A/B on the NEW base, by test id

| | failed | passed |
|---|---|---|
| bare `origin/main` v1.11.33, the 54 | **53** | 1 |
| this branch rebased onto it, the 54 | **12** | **42** |

**Closes 41. Introduces 0** (`comm -13` empty). The 12 that remain are the
*identical set* to the 12 measured on the old base — `diff` of the two sorted
lists is empty — so sixteen commits of PPA work moved none of this either way.

That bare-main figure is also the plainest possible confirmation of the
paragraph above: **the family is exactly as red on today's main as it was on
`867de4289`.** 53 of 54.

## 1. The one d8 red — both questions answered

### (a) Real finding about the tree, and not the one the message names

Not a stale pin. Seeding step 1.6x's one declared `required_output` with wrong
content and running its own gate command:

```
before  sha256 02998b14880f76689dc0f11b71cf4b512382d3e3fd811a96c5dc45...
rc=0
after   sha256 22bad440d577d4e24c168b4c98ce017377474622a0410e49d72d5f1...
```

The gate **overwrote** it. That path is the gate's own `--json` destination, so
no content can travel from it into the verdict. UNMOVED there is not "a gate
that stopped reading" — it is "there was no channel", which is the first of the
two cases the file's own docstring says must **not** be graded as blindness.

`_gradable` decided "is there a content channel" from the filename **suffix**. A
`.json` passed. The proxy is wrong for a class the repo can enumerate — four
steps (`1.6x`, `2`, `8`, `36`) declare a `required_outputs` set that is entirely
their own gate's `--json`/`--out` destinations, and `2` was already sitting in
the blind set for exactly this reason. So the fix is the stated rule
*implemented*, not relaxed. What the arm can no longer grade is **published and
asserted live** in `CONTENT_ARM_UNGRADABLE_SELF_WRITTEN`, in both directions.

### (b) The NORECORD rule is CORRECT. It was not relaxed.

The census is a claim about the whole grid derived from one nested session's rc.
A session red for a reason no cell represents makes that claim false, so
publishing a census from it would be the "measure something adjacent and report
it as the answer" disease. It is guarded in both directions by
`test_a_red_non_cell_helper_cannot_represent_the_nested_session_rc`, which
passes. **Seven measurements being unavailable because an eighth is red is the
right behaviour**; the answer was to fix the eighth.

Result: with d8 green the census block regenerated for the first time on this
branch — 552 cells, 552/552 accounted — and the 54 went **37 green -> 42**. One
fix, six IDs.

## 2. The diagnosis: it is (c), recorded in the commits — and worse than (c)

I read all three files. Taking the options in order:

**(a) collected but never made fatal — FALSE.** `gatekeeper-land.sh` runs the
selector (line 551) and pytest over it (line 614), and a failure sets `FAILED=1`
plus four further fatal checks: no junit summary, `NORECORD`, `NOTRUN`,
`AGGREGATE_NORECORD`. The verdict is emphatically fatal.

**(b) invoked from a path those landings did not take — TRUE as mechanism.** The
expensive tier deliberately lives in `gatekeeper-land.sh`, not the hook; the hook
only checks that the landing tool left `.git/gatekeeper-stamp`. The hook says why
in its own comment: *"Running them in a hook would make the hook slow enough to
be bypassed, and a bypassed hook enforces nothing."*

**(c) bypassed — TRUE, and it is now measured at 16 of 16.** Every one of the
sixteen commits main gained since `867de4289` — the whole v1.11.19..v1.11.33
batch, fourteen PPA lanes plus the PREPARE and the ACTIVATE — carries, verbatim
in its body:

> `LANDING GATE SKIPPED on the owner's instruction`

Sixteen for sixteen. Nothing in that batch was gated. The earlier reading (three
of fifteen) was a floor, not the rate.

And on the two commits that caused this family:

| commit | what it did | gate statement in its body |
|---|---|---|
| `7fcbc7397` | **added step 1.6x** | **none at all** |
| `bfa94460d` | wired 1.6x to an executor | "LANDED BY THE GATEKEEPER" *and* "LANDING GATE SKIPPED" |
| `867de4289` | retired 37.5self | "LANDED BY THE GATEKEEPER, **ROUND 2. Round 1 was refused for three new reds**" *and* "LANDING GATE SKIPPED" |

So: **yes, it is (c), and I am writing it down rather than softening it.**

**Two corrections that are in your favour, and both matter.**

First, `--no-verify` was not the operative mechanism *in this clone*, because
**the pre-push hook is not installed at all**: `/home/reyerchu/vibe-ic/.git/hooks/`
contains only the `.sample` files, and `core.hooksPath` is unset. There is
nothing there for `--no-verify` to skip. A plain `git push` would have enforced
exactly as much: nothing. The exposure is therefore larger than "a working hook
was bypassed" — that lane was never armed.

Second, `.git/gatekeeper-stamp` **does not exist** in this clone, so
`gatekeeper-land.sh` has never completed a landing here. And the stamp is
`.git`-local: it never enters a commit, so **whether the lane ran is not
auditable after the fact from the repository**. The only durable evidence is the
sentence a human chose to type in the commit body — which is why
`7fcbc7397` carrying none is significant.

The sharpest single fact: `867de4289` records that **round 1 was refused for
three new reds**, and it landed anyway under the skip.

Two other lanes reached this question from different measurements — one found an
always-run BLOCKING gate red across 13 landings, one found selected tests whose
red was never acted on. With 16 of 16 landings recording the skip, all three are
one disease: *the expensive tier is correct, is fatal, and is
not in the path anything actually took.*

## 3. The freshness mechanism — it already exists, and it was removed

You said "this existing gate, made fatal here" is a better answer if it is true.
It is true, and the repository predicted this exact failure **twice** before it
happened a third time. From `tools/ci/repo_hygiene_gates.sh`:

> *"`matrix_63x8/README.md` publishes the campaign's headline figure ... and it
> has gone stale TWICE, in two different ways, and neither time did anything
> notice."*

and, on leaving the enforcement gap open the second time:

> *"a generated artefact whose freshness check runs in no merge path will go
> stale again, and next time it may not be a number anyone re-derives."*

That prediction came true. The gate was then built, was **BLOCKING**, was green
on day one, and was **proven able to fail**. And on **2026-08-16 it was moved out
of the landing path** by owner decision, with this justification:

> *"a stale census breaks nothing ... `test_matrix_63x8_census_freshness.py`
> still enforces it in the suite, so the figure cannot drift unnoticed — it
> simply no longer sits between a fix and main."*

**That last sentence is the load-bearing false one.** The named safety net is the
suite — and the suite only enforces if the landing gate runs it. Five days later
the landing gate was skipped. The removal justification and the skip directive
are individually defensible and jointly fatal.

### Nothing changed on the enforcement side at v1.11.33

Re-checked on today's main, because `88328c9ca` moved `repo_hygiene_gates.sh`
and might have restored it: the census gate is still marked
`MOVED OUT OF THE LANDING PATH (owner decision, 2026-08-16)`, the pre-push hook
is still not installed (`.git/hooks/` holds only `.sample` files), and there is
still no `.git/gatekeeper-stamp`.

### The proposal, measured

Do not write a new gate. Put **`gen_matrix_63x8_census.py --check-figures`** in
the landing path. Proven at the commit that caused this:

```
$ cd <worktree at 7fcbc7397> && time python3 tools/gen_matrix_63x8_census.py . --check-figures
  [FAIL] test_matrix_d2_falsifiable.py:187  {figure:gated_steps} states 67; the tree says 69
[FAIL] 44 anchored figure(s) disagree with the tree
real  0m1.066s
rc=1
```

**It would have caught `7fcbc7397` at the moment it was made, in 1.07 seconds.**
That is the cheap half of the gate that was removed — it skips the ~64 s census
and re-derives the anchors only. The stated reason for removing the gate was
layering and cost; this half costs neither. The expensive half can stay where the
owner put it.

Two supporting items, both cheap:

* **Make the stamp auditable.** It lives only in `.git`, so no landed commit can
  be checked afterwards. Writing the verdict as a commit trailer would make
  "was this gated" a question the repository can answer instead of a sentence
  someone remembered to type.
* **Install the hook, or delete it.** An uninstalled `tools/git-hooks/pre-push`
  reads as protection that is not there. Either state is honest; the current one
  is not.

## 4. Per-ID table

| test id | bucket | root cause / what was done | fixed? |
|---|---|---|---|
| `test_matrix_63x8_census_freshness.py::test_the_census_block_is_fresh` | E | blocked by the one d8 red below — the nested outcome run is NORECORD while any red sits outside the cell join | YES |
| `test_matrix_63x8_census_freshness.py::test_the_published_total_equals_the_live_census` | E | blocked by the one d8 red below — the nested outcome run is NORECORD while any red sits outside the cell join | YES |
| `test_matrix_63x8_coverage.py::test_every_cell_has_a_live_outcome_and_the_outcome_run_is_not_starved` | E | blocked by the one d8 red below — the nested outcome run is NORECORD while any red sits outside the cell join | YES |
| `test_matrix_63x8_coverage.py::test_every_na_cell_asserts_a_live_precondition` | E | blocked by the one d8 red below — the nested outcome run is NORECORD while any red sits outside the cell join | NO |
| `test_matrix_63x8_coverage.py::test_live_collection_relays_finite_semantic_progress_past_old_bound` | D | timing-sensitive under load; 6/6 green in isolation | YES |
| `test_matrix_63x8_coverage.py::test_no_cell_is_counted_enforced_while_its_predicate_is_red` | E | blocked by the one d8 red below — the nested outcome run is NORECORD while any red sits outside the cell join | NO |
| `test_matrix_63x8_coverage.py::test_the_enforcement_census_is_reported_for_humans` | E | blocked by the one d8 red below — the nested outcome run is NORECORD while any red sits outside the cell join | YES |
| `test_matrix_63x8_coverage.py::test_the_grid_size_is_computed_from_the_live_flow_yaml` | A | GRID_AS_MEASURED/STEP_IDS_AS_MEASURED pinned a 67-step grid; 0.5ic and 1.6x arrived, 37.5self left | YES |
| `test_matrix_63x8_ledger.py::test_absent_from_audit_is_surfaced_not_swallowed` | A | EXPECTED_CELLS 544 -> 552 | YES |
| `test_matrix_63x8_ledger.py::test_accessors_track_a_removed_field` | A | EXPECTED_* tripwires +1 | YES |
| `test_matrix_63x8_ledger.py::test_blocks_on_presence_is_not_the_same_set_as_non_empty` | A | CENSUS_BLOCKS_ON_PRESENT 68 -> 69 | YES |
| `test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[1]` | A | EXPECTED_STEPS 68 -> 69 | YES |
| `test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[2]` | A | EXPECTED_STEPS 68 -> 69 | YES |
| `test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[3]` | A | EXPECTED_STEPS 68 -> 69 | YES |
| `test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[4]` | A | EXPECTED_STEPS 68 -> 69 | YES |
| `test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[5]` | A | EXPECTED_STEPS 68 -> 69 | YES |
| `test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[6]` | A | EXPECTED_STEPS 68 -> 69 | YES |
| `test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[7]` | A | EXPECTED_STEPS 68 -> 69 | YES |
| `test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[8]` | A | EXPECTED_STEPS 68 -> 69 | YES |
| `test_matrix_63x8_ledger.py::test_every_coordinate_appears_exactly_once` | A | EXPECTED_CELLS 544 -> 552 | YES |
| `test_matrix_63x8_ledger.py::test_gate_presence_matches_the_yaml` | A | CENSUS_GATE_PRESENT 67 -> 68 | YES |
| `test_matrix_63x8_ledger.py::test_gate_programs_non_empty_exactly_where_the_gate_names_one` | A | CENSUS_GATE_PROGRAMS_NON_EMPTY 66 -> 67 | YES |
| `test_matrix_63x8_ledger.py::test_ledger_is_the_live_cross_product` | A | EXPECTED_STEPS 68 -> 69 | YES |
| `test_matrix_63x8_ledger.py::test_ledger_tracks_a_mutated_flow` | A | mutated-flow arithmetic 552 -> 560 | YES |
| `test_matrix_63x8_ledger.py::test_output_entries_classify_into_the_four_kinds` | A | entries 161 -> 162, FILE 119 -> 120 (1.6x's one plain FILE) | YES |
| `test_matrix_63x8_ledger.py::test_required_outputs_non_empty_exactly_where_declared` | A | CENSUS_REQUIRED_OUTPUTS_PRESENT 66 -> 67 | YES |
| `test_matrix_63x8_ledger.py::test_total_steps_field_is_not_the_step_count` | A | EXPECTED_STEPS 68 -> 69 | YES |
| `test_matrix_d1_wiring.py::test_probe_declared_programs_array_orphans_are_pinned` | A | ORPHAN_DECLARED_PROGRAMS missed 1.6x's two producers (7fcbc7397) and 0.5ic/tapeout_declaration_gen (00d9dc261) | YES |
| `test_matrix_d2_falsifiable.py::test_d2_gate_has_a_reachable_fail[step1.6x]` | C | EMPTY fixture cannot reach an optional-subject gate's fail branch; new CROSSLAYER_SEARCH_UNDECLARED fixture, mapped to that one clause | YES |
| `test_matrix_d3_outputs_produced.py::test_d3_cell_states_partition_all_steps` | A | (ENFORCED,WAIVED,NA) pinned (51,2,15); 1.6x lands ENFORCED -> (52,2,15) | YES |
| `test_matrix_d3_outputs_produced.py::test_d3_manifest_covers_exactly_the_flow_steps` | A | per-dimension population pin 68 -> 69 | YES |
| `test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step15]` | E | manifest cites a 'home'-kind campaign run root no corpus can supply; pre-existing (cited 7x both before and after 1.6x) | NO |
| `test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step17]` | E | manifest cites a 'home'-kind campaign run root no corpus can supply; pre-existing (cited 7x both before and after 1.6x) | NO |
| `test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step19]` | E | manifest cites a 'home'-kind campaign run root no corpus can supply; pre-existing (cited 7x both before and after 1.6x) | NO |
| `test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step20]` | E | manifest cites a 'home'-kind campaign run root no corpus can supply; pre-existing (cited 7x both before and after 1.6x) | NO |
| `test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step30]` | E | manifest cites a 'home'-kind campaign run root no corpus can supply; pre-existing (cited 7x both before and after 1.6x) | NO |
| `test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step32]` | E | manifest cites a 'home'-kind campaign run root no corpus can supply; pre-existing (cited 7x both before and after 1.6x) | NO |
| `test_matrix_d4_criteria_match.py::test_d4_selfcheck_every_cell_has_exactly_one_disposition` | A | per-dimension population pin 68 -> 69 | YES |
| `test_matrix_d5_deps_correct.py::test_d5_covers_every_cell_exactly_once` | A | per-dimension population pin 68 -> 69 | YES |
| `test_matrix_d5_deps_correct.py::test_d5_state_census_is_exhaustive` | A | per-dimension population pin 68 -> 69 | YES |
| `test_matrix_d6_skip_discipline.py::test_d6_skip_discipline[step1.6x]` | C | L1b knew 3 of the flow's 4 disclosure markers; __JSON_VACUOUS_HINT__ (#901) added, read off flow_compliance_check | YES |
| `test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step31]` | B | step 31 never declares reports/phase3/drc_signoff.json, which drc_report_check writes and general_precheck reads | NO |
| `test_matrix_d7_outputs_list_complete.py::test_every_cell_lands_in_exactly_one_state` | A | per-dimension population pin 68 -> 69 | YES |
| `test_matrix_d8_missing_caught.py::test_a_readable_artefact_that_is_wrong_is_not_worth_the_same_as_a_right_one` | B | step 1.6x's only declared output is the checker's OWN report, so corrupting it cannot move the verdict; the test refuses pinning and is right | YES |
| `test_matrix_d8_missing_caught.py::test_d8_a_present_but_wrong_declared_output_is_measured_not_assumed` | A | CONTENT_ARM_AS_MEASURED gains 1.6x, measured UNMOVED | YES |
| `test_matrix_d8_missing_caught.py::test_d8_downgrade_is_reachable_through_each_steps_own_real_gate` | A | REAL_GATE_PASS_TIER_STEPS gains 1.6x (set grew, did not shrink) | YES |
| `test_matrix_d8_missing_caught.py::test_d8_only_one_declared_output_present_is_still_missing[step1.6x]` | A | same pin; 1.6x was single-entry and unpinned | YES |
| `test_matrix_d8_missing_caught.py::test_the_pin_is_the_MEASURED_population_not_a_SUPERSET_of_it` | A | SINGLE_ENTRY_STEPS_AS_MEASURED re-derived, 26 -> 27 members (1.6x declares one output) | YES |
| `test_matrix_mutation_ledger.py::test_every_enforced_cell_carries_a_named_mutation[step0.5ic]` | E | 1.6x/d3 and 0.5ic/d3 are ENFORCED but their mutation is NOT_REPLAYABLE (no corpus) / ALREADY_RED (with corpus) | NO |
| `test_matrix_mutation_ledger.py::test_every_enforced_cell_carries_a_named_mutation[step1.6x]` | E | 1.6x/d3 and 0.5ic/d3 are ENFORCED but their mutation is NOT_REPLAYABLE (no corpus) / ALREADY_RED (with corpus) | NO |
| `test_matrix_mutation_ledger.py::test_the_coverage_is_complete_and_the_count_is_stated` | E | 1.6x/d3 and 0.5ic/d3 are ENFORCED but their mutation is NOT_REPLAYABLE (no corpus) / ALREADY_RED (with corpus) | NO |
| `test_matrix_mutation_ledger.py::test_the_flow_declares_no_step_the_ledger_never_measured` | A | 12 mutations replayed against 1.6x, all REDDENED | YES |
| `test_matrix_mutation_ledger.py::test_the_grid_gate_names_the_cell_that_moved` | A | LEDGER_AS_MEASURED (68,8,514) -> (69,8,522) | YES |
| `test_matrix_mutation_ledger.py::test_the_ledger_grid_matches_what_was_measured` | A | same, plus 1.6x now measured | YES |

Bucket key: **A** stale generated census/ledger, **B** flow is wrong, **C**
matrix logic is wrong, **D** harness artefact, **E** genuinely open.

Two rows changed bucket since the first RESULT.md, on measurement:
`test_a_readable_artefact_that_is_wrong_...` was filed **B** and is **C** — the
matrix's gradability proxy, not the flow; and the six coverage/census IDs filed
**E (cascade)** were correct as filed and five of them are now green.

## 5. The last 12, as one graph

```
6 x d3 [step15,17,19,20,30,32]  manifest cites a 'home'-kind campaign run root
                                no corpus can supply  (pre-existing: cited 7x
                                both before and after 1.6x)
1 x d7 [step31]                 step 31 never declares
                                reports/phase3/drc_signoff.json, which its own
                                gate writes and general_precheck reads
        |
        +--> test_no_cell_is_counted_enforced_while_its_predicate_is_red
             names exactly those SEVEN and nothing else
        +--> test_every_na_cell_asserts_a_live_precondition

3 x mutation ledger             1.6x/d3 and 0.5ic/d3 are ENFORCED but their
                                mutation is NOT_REPLAYABLE (no corpus) /
                                ALREADY_RED (with corpus)
```

The two coverage IDs are **not independent findings** — they are the aggregate
of the seven above and will go green with them. That is why the honest count of
open *defects* here is **9**, not 12.

`test_d7_required_outputs_list_is_complete[step31]` is still a one-line flow fix
I have not made, for the reason given last time and re-checked: adding a
`required_outputs` entry moves `required_output_entries` 162 -> 163 and `FILE`
120 -> 121, reddening ledger pins this branch just set, and may redden step
31/d3 (currently green) if no published run carries the artefact. It wants its
own change with its own re-measurement.

## 6. Mutation arms

Every fix ships with one. Reverting each in a scratch copy and re-running:

```
FAILED tests/test_matrix_d2_falsifiable.py::test_d2_gate_has_a_reachable_fail[step1.6x]
FAILED tests/test_matrix_d6_skip_discipline.py::test_d6_skip_discipline[step1.6x]
2 failed, 1 warning in 3.20s
```

The twelve mutation rows carry their arm by construction — each was
`--replay <NAME> --step 1.6x` -> REDDENED before being written down, and
`test_lock3_every_entry_is_arithmetically_consistent_with_its_own_evidence`
caught my first attempt, which moved `applies_to` without `measured.reddened`.
The d8 change is arm-checked by its own two-direction assertion on
`CONTENT_ARM_UNGRADABLE_SELF_WRITTEN`.

## 7. By-TEST-ID A/B against origin/main

Serially, in the container, `-p no:randomly -p no:pytest_ethereum`:

| | failed | passed |
|---|---|---|
| `867de4289`, the 54 | 53 | 1 |
| this branch, the 54 | **12** | **42** |

Whole-file A/B on the file this branch changes most,
`test_matrix_mutation_ledger.py`: 24 failed at the base, 21 here, `comm -13`
**empty — zero introduced**. d6 is `80 passed, 1 xfailed`; d8 is `343 passed`.

## REQUESTS TO THE LANDER

1. **Already rebased onto v1.11.33 and re-measured there.** The fourteen PPA
   lanes have landed; this branch sits on top of them, the rebase was clean, and
   the result is identical: 12 red, the same 12. Nothing further is needed from
   you on ordering.
0. **This branch has NOT landed, whatever the tracker says.** Searched by content
   on `origin/main`: `CONTENT_ARM_UNGRADABLE_SELF_WRITTEN` 0,
   `CROSSLAYER_SEARCH_UNDECLARED` 0, `EXPECTED_STEPS = 69` 0. Bare main still
   measures 53 of 54 red. If something reported it landed as v1.11.44, that
   report is wrong and worth chasing — v1.11.34+ do not exist on this remote.
2. **Version not bumped**; `plugin.json` and both `marketplace.json` untouched.
3. **No `--write-baseline` on any hygiene gate.** The census block and the
   anchored figures were regenerated by the repository's own
   `tools/gen_matrix_63x8_census.py --fix`, which is the documented repair for a
   derived document whose staleness was the defect.
4. **Section 3 is the actionable one.** `--check-figures` in the landing path is
   1.07 s and would have caught the causing commit. It is the cheap half of a
   gate this repo already wrote, already proved could fail, and removed.
5. **Section 2 concerns the landing procedure, not this branch.** I have written
   it as measured, including the two points that cut in your favour: the hook was
   never installed, so `--no-verify` was not what disarmed it; and the stamp is
   not auditable after the fact, so "was this gated" cannot be answered from the
   repository.
6. **The 38 other red IDs of main's 92 are not mine and were not investigated.**
>>>>>>> origin/jmatrix/63x8-main-reds
=======
# PPA layer — a test suite for the LAYER, run, and what it found

**Base:** `e36d81c0a` (v1.11.33), cut from `origin/main` at 2026-08-21 10:34 UTC+8.
**Branch:** `agent/jppa-tests`. **Worktree:** `/home/reyerchu/_jppatests`.
**Version:** not bumped, per the brief. **Protected paths:** none touched (proof below).

Every number here traces to a command in this file. Where I did not measure
something I have written `NOT_MEASURED` rather than a default.

---

## 0. One thing I could not get

`ppa-e2e/FINDINGS.md` **does not exist** anywhere I can reach. Searched:

```
$ git ls-tree -r --name-only origin/main | grep -i 'ppa-e2e\|FINDINGS'   # nothing
$ git log --all --oneline --diff-filter=A -- '*ppa-e2e*'                 # nothing
$ find /home/reyerchu -maxdepth 6 -type d -name 'ppa-e2e'                # nothing
$ grep -rl "required_views" /home/reyerchu --include=*.md                # nothing
$ cd ~/benchmark-data && git ls-tree -r --name-only origin/main | grep -i ppa   # nothing
```

So I have the **five findings your brief names** (F-2, F-4, F-5, F-10, F-11) and
**not the other thirteen**. All five are reproduced below with a command. For the
thirteen I do not have, I drove the layer myself and found **six more defects**,
which are in §2 — but I cannot tell you which of them are your F-1/F-3/F-6…, and
I have not written tests for findings I have never read. **Send me the file and
I will finish that half.**

---

## 1. The A/B, by TEST ID

Counts are given because you asked for them, but the sets are what matter — and
the sets are disjoint in the right direction.

| | base `e36d81c0a` | branch | delta |
|---|---:|---:|---|
| `test_*ppa*` files | 46 | 53 | +7 |
| collected | 1219 | 1362 | +143 |
| **FAILED** | **33** | **0** | −33 |
| passed | 1185 | 1324 | |
| skipped | 1 | 14 | +13, all declared (§4) |
| xfailed | 0 | 24 | +24, all `strict=True` pins (§3) |

```
$ python3 -m pytest $(ls programs/tests/test_*ppa* ) -q -p no:randomly --tb=no -rf
  base   33 failed, 1185 passed, 1 skipped in 56.96s
  branch 1324 passed, 14 skipped, 24 xfailed in 62.47s
```

By test ID:

```
$ comm -23 ab_base.txt ab_mine.txt | wc -l     # red on base, green on branch:  33
$ comm -13 ab_base.txt ab_mine.txt | wc -l     # green on base, red on branch:   0
```

**Every one of the 33 base failures is accounted for, and I introduced no new red.**
Three were fixed by the `ppa_contract_check` repair in §2.5; the other 30 were one
root cause, §4.

Wider net — the 61 files that touch any patched program, run serially:

```
$ python3 -m pytest <61 files> -q -p no:randomly --tb=no -rf
  1 failed, 1641 passed, 14 skipped, 24 xfailed in 107.32s
```

The one failure is `test_not_verified_tier.py::test_no_new_undeclared_infrastructure_skip_appears`
and it is **red on pristine base with byte-identical output**, naming
`test_trusted_pytest_entry.py` — not a file of mine. Not caused by this branch;
not fixed by it either.

### The same run on a fully-provisioned host

The host ships `jsonschema 3.2.0`. I built a throwaway venv with `jsonschema
4.26.0` + `pyyaml` (in the scratchpad; **nothing installed on your machine**) to
find out whether the 30 base reds were hiding real defects:

```
$ <scratchpad>/venv/bin/python -m pytest <61 files> -q -p no:randomly --tb=no -rf
  1 failed, 1672 passed, 5 skipped, 24 xfailed in 103.60s
```

**They were not.** With a real draft-2020-12 validator the schema layer is clean:
`test_ppa_contract.py` + `test_ppa_contract_fixtures.py` +
`test_ppa_metrics_schema_agreement.py` = **92 passed**. The 33 were a host
condition reported as code failures.

---

## 2. What I changed, and why, per item

Seven fixes. Every one has a mutation arm in §5 that I **ran**.

### 2.1 The bad-invocation arm — 12 of 14 CLIs, measured

```
$ for f in programs/ppa_*.py; do out=$(python3 "$f" --this-flag-does-not-exist 2>&1); echo "$? $f"; done
  12 of 14 exited 2;  ppa_feasibility_check and ppa_pareto_check exited 3
```

`PPA_INTERFACES.md` §1 gives 3 to a bad invocation. `argparse` exits **2**, which
here means UNDETERMINED. That is not pedantry: §1 also says rc=2 must never be
mapped to PASS, and the way a flow gate honours that is to treat 2 as "nothing to
check here" — so a misspelled flag reads as a step with nothing to do and the run
carries on green having measured nothing.

### 2.2 …and the trap its obvious fix walks into

The two programs that had already fixed 2.1 did it with a bare
`except SystemExit: return RC_BAD_INVOCATION`. `--help` is also `SystemExit`, with
code 0:

```
$ for f in programs/ppa_*.py; do python3 "$f" --help >/dev/null 2>&1; rc=$?; echo "$rc $f"; done
  ppa_feasibility_check.py  rc=3
  ppa_pareto_check.py       rc=3
```

Asking a program what its flags are is not a bad invocation. **These two are the
same defect from opposite sides, which is why fixing either alone produces the
other** — so both are fixed in one place.

**New file `programs/_ppa/cli_exit.py`** (sha256 `52bc4f47…`, 4.0 KB) — reads
`exc.code` rather than catching the type: 0/None → rc 0, anything else → rc 3.
Applied to the **11 programs this branch owns**. Also `cli_exit.refuse()` for a
usage error found *after* parsing (`ap.error(...)` exits 2 as well) — 5 sites.

### 2.3 `ppa_predict_aggregate.py --cell-count 0` → rc **0**, publishing zeroes

```
$ python3 programs/ppa_predict_aggregate.py --cell-count 0 ; echo rc=$?
  - **Estimated area**: 0.0 um² (0.0000 mm²)
  - **Estimated power**: 0.00 uW
  rc=0
```

§2: "No numeric sentinels. `0`, `-1` and `""` never mean 'not measured'." A cell
count of zero is not a design with no cells; on every path that reaches this CLI
it is a count that was never taken. **Now rc=2 `[CANNOT CHECK]`, and no estimate
is printed at all** — a refusal that still prints the number gets the number
picked up downstream.

### 2.4 `ppa_metric_extract.py` → rc **0** over an empty record set

```
$ echo '{"schema":"vibeic.ppa.metric_bundle.v1","records":[]}' > b.json
$ python3 programs/ppa_metric_extract.py --records b.json ; echo rc=$?
  ppa_metric_extract: 1 document(s) named, 1 read, 0 unreadable, 0 record(s) indexed, 0 refused
  rc=0
```

The program **already** guarded `n_docs == 0`, with the comment *"An empty bundle
would read as a clean run."* A document that WAS read and holds zero records
produces the identical empty bundle. Same sentence, one level in, unguarded.
Now rc=2 with `code: EMPTY_RECORD_SET`.

### 2.5 `ppa_contract_check.py` → an internal error reported as **rc=1**

```
$ python3 programs/ppa_contract_check.py --contract c.json ; echo rc=$?
  AttributeError: module 'jsonschema' has no attribute 'Draft202012Validator'
  rc=1
```

The program guards `ImportError` on jsonschema, honestly, with *"This is not the
schema passing."* It does not guard **jsonschema present but older than 4.0**, so
the `AttributeError` escapes `raise SystemExit(main())` and the process exits
**1** — which §1 reserves for *a finding about the design*. **A missing library was
indistinguishable from a broken contract**, and unlike a 2 (which a caller may
skip) a 1 stops a sign-off with a finding nobody can act on.

Fixed two ways: the `hasattr` guard now returns an UNDETERMINED `PPA-C-010`
finding naming the version, and `__main__` catches any unexpected exception and
returns 3. This alone turned **3** of the 33 base reds green.

### 2.6 `ppa_head_to_head_check.py` — an honest refusal with the wrong marker

Printed `VACUOUS: … This is NOT a pass … rc=2.` — correct in English, but §1
requires `[CANNOT CHECK]` / `[REFUSE]` **so that a 2 can be found by grep**. Marker
added. (See §5, arm 6: my first version of this arm **could not go red**.)

### 2.7 `ppa_area_threshold_check.py` — bare `ERROR:` on four refusals

Three "artefact not found" cases printed `ERROR: …` and returned 2 with no marker.
Marker added. The fourth, *"provide `--threshold-pct` or `--prompt`"*, is a
statement about **argv**, not about an artefact — moved from rc=2 to rc=3.

### 2.8 Three tests that were wrong, fixed as tests

Not relaxed — tightened to the contract. Each is a case where the test pinned a
*mechanism* instead of the *behaviour*, and its own docstring already stated the
right intent.

| test | pinned | now |
|---|---|---|
| `test_ppa_page_claim_check::test_bad_invocation_is_not_a_design_finding` | `SystemExit.code == 2  # argparse's own; never 1` | `main([]) == 3` |
| `test_ppa_report_gen::test_bad_invocation_is_not_a_design_finding` | same | same |
| `test_v1_0_85_issue768…::test_acceptance_reference_flag_in_help` | `pytest.raises(SystemExit)` | `main(["--help"]) == 0` **and** the `--reference` grep |

The first two say *"rc=1 is a claim about silicon (§1). Arg errors must not borrow
it"* and then assert **2**, which is argparse's default and §1's UNDETERMINED. The
intent was right; the value was the wrong one of the two remaining codes. The
third asserted that `main(["--help"])` *raises*, which is a fact about argparse's
internals — the issue's acceptance command greps the help text, and that is now
asserted directly, plus the exit code, which is strictly more than before.

---

## 3. The new suite — 7 files, 165 tests

Named `test_ppa_layer_*` so they are addressable as a set. **Every arm is
parametrized by program or metric name**, so a red names the thing, not an index.

| file | tests | green | pinned |
|---|---:|---:|---:|
| `test_ppa_layer_exit_contract.py` | 72 | 69 | 3 |
| `test_ppa_layer_producer_consumer.py` | 36 | 24 (+2 skip) | 10 |
| `test_ppa_layer_backend_seam.py` | 17 | 12 | 5 |
| `test_ppa_layer_internal_error_is_not_a_finding.py` | 17 | 17 | 0 |
| `test_ppa_layer_vacuous_population.py` | 13 | 12 | 1 |
| `test_ppa_layer_feasibility_view_scope.py` | 6 | 3 | 3 |
| `test_ppa_layer_timing_view_dedup.py` | 4 | 2 | 2 |

Two structural choices, both because the alternative is how coverage rots:

* **Populations are DISCOVERED, not listed.** `ppa_*.py`, `_ppa/backends/*.py`,
  `area.AREA_METRICS`, `feasibility.DEFAULT_AXES` — a fifteenth program or a
  sixth backend is covered the day it lands.
* **Every discovered population has its size ASSERTED FIRST.** A glob that finds
  nothing makes every parametrized arm below vacuously green, which is this
  suite's own subject matter turned on itself.

### 3.1 The five E2E findings — reproduced, then pinned

Each is `xfail(strict=True)`: when the owning lane lands its fix the test
**XPASSes and the file goes red**, forcing the pin out. A pin that survives its bug
is a second bug, and it is the one that hides the first. §5 proves this fires.

**F-2 — `--backend` drives no backend, including the ones that exist.**
All 5 shipped backends and a misspelling return the same rc=2. The refusal is
*honest* (the module comment says an empty bundle for an undriven tool is exactly
the defect the contract removes), so I pinned only the "actually extracts"
arm — and added two arms that must stay green, because the wrong fix here is
"return 0 and write an empty bundle".
*Why no per-module test saw it: the flag was never invoked at all.*

**F-4 — three producers emit envelopes the canonical consumer REFUSES.**
Measured, driving each producer from its **own shipped fixtures**:

| producer | result |
|---|---|
| `power.metric_records` | **48 of 48 records refused** — `SCOPE_SENTINEL: scope.liberty is None` |
| `timing.timing_rows` | every row refused; **`MetricIndex.add` raises** `scope.stage is required` + 4× SCOPE_SENTINEL |
| `area.area_record` | 3 of 14 metrics refused (that is F-5) |

*Why no per-module test saw it:* `test_ppa_power.py` checks power's rules against
power's records; `test_ppa_metrics.py` checks metrics' rules against records built
by `metrics.measured()`. **Not one test ever hands a producer's output to
`metrics.validate`** — so the only property that makes the shared `schema` string
mean anything was tested by nobody.

The tests deliberately do **not** assert which side is right. Whether `liberty:
None` should be dropped or `validate` should accept a declared-absent scope field
is the record lane's call, and either makes them green.

**F-5 — the area lane's declared unit and the metrics lane's required unit disagree.**

```
area.proxy.cell_count       area says 'cells'      metrics requires 'count'
area.proxy.wire_count       area says 'wires'      metrics requires 'count'
area.proxy.wire_bit_count   area says 'wire_bits'  metrics requires 'count'
```
3 of 14. Each module is self-consistent; the pair is not.

*A correction to my own first probe:* I initially reported power as worse still,
`power.total_mw` carrying `unit="W"`. That metric name is mine, not the
producer's — power really emits `power.total_w`, and all four of its names agree
with their unit. The real power defect is the scope sentinel above.

**F-10 — every timing row emitted twice from byte-identical files.**
`timing.discover_reports` de-duplicates by **resolved path**, and a Phase-3 tree
carries the same sign-off report under `phase3/stage3/sta/` and
`reports/phase3/sta/`. Measured on two copies with one sha256:

```
rows: 8      distinct row_digest: 8      distinct (metric, scope): 4
metrics.record_key collisions: 4 of 4
```

*Why no per-module test saw it, and this is the interesting half:* the obvious
assertion **does not fire**. `row_digest` covers `source.path`, so the two copies
hash differently and `len(set(digests)) == len(rows)` passes **with the bug
present**. The duplication is visible only at `metrics.record_key` — the key the
timing lane never tested and the metrics lane never fed timing rows to. I left a
green test asserting that `row_digest` cannot see this, so the next author does
not reach for the instrument that already failed.

**F-11 — `required_views` is global, so one view poisons every axis.**
The widest blast radius of the five. One tuple is applied to all nine axes; six of
them (drc, lvs, antenna, ir, em, equivalence) are not per-corner facts at all.
Measured on a candidate **clean on all nine axes and measured at both declared
corners**:

| `required_views` | verdict | axes SATISFIED |
|---|---|---:|
| `()` | UNDETERMINED | 0/9 |
| one stage-only view | **FEASIBLE** | **9/9** |
| the two real STA corner views | UNDETERMINED | **0/9** |

The hard promotion gate returns FEASIBLE **only** when `required_views` holds a
single view so weak every axis satisfies it. Declare what a sign-off actually
declares and it can pass nothing — a gate that cannot be satisfied, which is the
mirror of a gate that cannot fail and just as useless. Even setup and hold poison
each other: a setup record can never cover the hold view.

*Why no per-module test saw it:* the feasibility suites exercise one axis at a
time with `required_views` matched to that axis. The defect is a property of the
**cross product**, and no test ever put a timing view and a DRC record in one
policy.

I also added a green test that empty `required_views` stays UNDETERMINED, so a
fix for F-11 cannot quietly take out the rule it was built to enforce.

### 3.2 The four arms, over the whole layer

`POSITIVE / NEGATIVE / VACUOUS / BAD INVOKE` for all 14 CLIs, discovered by glob.
The vacuous arm is split in two on purpose, because only the easy half was
reachable before:

* **absent** input — one shape for every program. Green across the layer.
* **present, well-formed, and EMPTY** — a different document per program: a bundle
  with `records: []`, a space with no lever, `candidates: []`, an empty corpus dir.
  This is where §2.3, §2.4 and the pinned `ppa_search_run` finding live. The file
  opens, the parse succeeds, the population is zero, and
  `for x in population: check(x)` falls straight through to 0.

---

## 4. The 30 remaining base reds — one cause, and it is the same shape again

All 30 were `jsonschema 3.2.0` lacking `Draft202012Validator`.
`test_ppa_metrics_schema_agreement.py` opens with an `importorskip` whose reason
says, correctly:

> *"This is a SKIP and not a pass: nothing here looked."*

and covers exactly one of the two ways the validator can be unavailable. **That is
the fourth time this layer guards one level too shallow** — with §2.4
(`n_docs == 0`), §2.5 (`ImportError`), and `ppa_predict_aggregate` citing §2 on
sentinels in its docstring while estimating from zero. That family is what
`test_ppa_layer_internal_error_is_not_a_finding.py` is about.

**New file `programs/tests/_ppa_jsonschema.py`** (sha256 `5eb6dbec…`): one
capability check, `HAVE_DRAFT_2020_12`, plus a `needs_draft_2020_12` marker.
Applied to the 9 affected tests in `test_ppa_contract.py`, the 1 in
`test_ppa_contract_fixtures.py`, and as a module guard on the agreement file.

**It routes through `not_verified_tier`, not through a bare `pytest.skip`.** A
plain skip is the same lie one level up — `test_not_verified_tier.py` exists
because an infrastructure-shaped skip that bypasses the tier is invisible to the
roll-up (vibe-ic#1128). So the run now says:

```
[NOT VERIFIED] 2 test(s) did NOT run their verification because what they verify
WITH was out of reach. These are NOT passes …
  2 x NOT_VERIFIED: jsonschema 3.2.0 has no Draft202012Validator (it arrived in
  4.0) … — remedy: python3 -m pip install 'jsonschema>=4'
```

An unanswered question with the command that answers it, instead of 30 reds that
say nothing true or 30 quiet green ticks. And §1 confirms the questions are
answerable: **92 passed** under the venv.

---

## 5. Mutation arms — every fix, reverted, named test confirmed red

Each was run: revert, run the named test, restore. `MUTATION APPLIED` was asserted
by the mutating script itself, because a replacement that silently does not match
proves nothing.

| # | fix reverted | named test | result |
|---|---|---|---|
| 1 | `cli_exit` returns argparse's 2 again | `…exit_contract::test_unknown_flag_is_bad_invocation_not_undetermined` | **11 failed** |
| 2 | `cli_exit` back to bare `except SystemExit` | `…::test_help_is_not_a_bad_invocation` + `…::test_cli_exit_helper_tells_help_from_usage_error_by_code` | **12 failed** |
| 3 | drop `report["records"] == 0` | `…vacuous_population::test_mutation_metric_extract_empty_bundle` | **1 failed** |
| 4 | drop the `cell_count <= 0` guard | `…vacuous_population::test_mutation_predict_aggregate_zero_cells` | **1 failed** |
| 5 | drop the `Draft202012Validator` guard | `…internal_error…::test_contract_check_never_exits_one_because_of_the_validator` + `…::test_contract_check_says_the_schema_was_not_applied` | **2 failed** |
| 6 | drop the `[CANNOT CHECK]` marker | `…vacuous_population::test_a_present_but_empty_population_is_never_a_pass[7]` | **1 failed** |
| 7 | revert markers to bare `ERROR:` | `…exit_contract::test_vacuous_refusal_is_marked[ppa_area_threshold_check.py]` | **1 failed** |

Each restored cleanly (`69 passed, 3 xfailed`; `12 passed, 1 xfailed`).

### Arm 6 failed to fail, and that is the useful part

The first time I ran it, the mutation applied (asserted), the marker verifiably
vanished from the program's output, and **the suite stayed green: 14 passed.** My
vacuous table reached `ppa_head_to_head_check` by the *absent-record* path, which
is a different branch from the *empty-corpus* path where the marker lives. A guard
that cannot go red is not a guard. I added the empty-corpus case (now case 7 of 8)
and re-ran; it goes red. Both fixes for the two positive-control fixes
(`test_mutation_metric_extract_still_passes_on_a_real_record`,
`…_still_estimates_a_real_count`) exist for the mirror reason: an unconditional
`return 2` would also have made the arms green.

### The strict pins fire too

Not asserted from pytest semantics — **run**. I simulated the record lane landing
F-5 (`'cells' → 'count'` in `_ppa/area.py`):

```
6 failed, 24 passed, 2 skipped, 4 xfailed
    …test_area_declared_unit_matches_the_unit_the_name_requires[area.proxy.cell_count]  … ×3
    …test_area_record_is_accepted_by_the_canonical_consumer[area.proxy.cell_count]      … ×3
```

Exactly the six pins, red on the fix, forcing their own removal. Restored.

---

## 6. What I could NOT settle

* **13 of the 18 E2E findings.** §0. Not guessed at, not invented.
* **Whether F-4 is the producers' bug or the consumer's.** Deliberate: both
  resolutions make the tests green and the choice is the record lane's.
* **The six defects in §2 that I found myself are not mapped to your finding
  numbers.** Some are probably among the thirteen; I cannot tell which.
* **`ppa_search_run.py` on a real trials document.** I exercised the plan path and
  the empty-space path. Driving a full search was out of scope for a test lane and
  is `NOT_MEASURED`.
* **§1 stream discipline.** `ppa_contract_check` puts its human summary on
  **stderr**; §1 says stdout, refusals on stderr. I noticed this while debugging
  one of my own wrong assertions and did **not** sweep the layer for it — asserting
  it could redden other lanes' files on a clause I have not measured everywhere.
  `NOT_MEASURED` across the other 13 programs. Worth a follow-up.
* **`test_ppa_actuator_registry.py` and `test_ppa_closure_state_machine.py`
  `import yaml` at module scope with no guard** — a COLLECTION ERROR, not a skip,
  on a host without pyyaml. Same family as §4. Not fixed: not my lane's files and
  the host has pyyaml, so it is a latent condition rather than a live red.
* **`test_not_verified_tier::test_no_new_undeclared_infrastructure_skip_appears`**
  is red on base and on this branch with identical output, naming
  `test_trusted_pytest_entry.py`. Not mine, not touched.
=======
# The record producers and the record consumer, made to agree

Branch cut from `origin/main` at **`e36d81c0a`** — `landing(ACTIVATE): wire what
the fourteen lanes shipped` **[v1.11.33]**. Fetched 2026-08-21; that is the tip
`origin/main` actually carries. The brief named a v1.11.19..v1.11.47 batch — the
last eleven of those (v1.11.34..v1.11.47) are not on `origin/main` from here, so
this branch is cut from v1.11.33 and everything below is measured against it.

Items: **F-2, F-4, F-5, F-9, F-13** and lander requests **R5, R6, R7, R8, R10**.

Every fix has two halves, because shipping only the first is what lets these
come back: the code is reconciled, **and the rule that was missing is written
into `docs/PPA_INTERFACES.md` with a test that fails if the two sides drift
again**. The contract gained one new subsection per class of disagreement:
**§2** (the unit rule), **§2.1** (a second record under one identity), and
**§3.1** (the five identities, and what belongs in each).

---

## What changed, per item — and WHICH SIDE moved

### F-5 / R6 — the unit of a count · **the PRODUCER moved**

`_ppa/area.py` declared `"cells"`, `"wires"` and `"wire_bits"`; `_ppa/metrics.py`
reads the `_count` suffix on a metric NAME as a claim about `unit` and demanded
`"count"`. Two files in one lane holding opposite rules. **Three** specs were
wrong, not one — the finding named `cell_count`, and `wire_count` and
`wire_bit_count` have the same defect:

```
area.proxy.cell_count      area.py says 'cells'      name claims 'count'  -> UNIT_CONTRADICTS_NAME
area.proxy.wire_count      area.py says 'wires'      name claims 'count'  -> UNIT_CONTRADICTS_NAME
area.proxy.wire_bit_count  area.py says 'wire_bits'  name claims 'count'  -> UNIT_CONTRADICTS_NAME
```

**`_ppa/area.py` is the side that changed.** The metric NAME is part of the
record's identity, and `unit_suffix_of` is the only cross-check in the system
positioned to catch an order-of-magnitude unit error — every consumer downstream
trusts `unit`. Relaxing `metrics.py` to accept `"cells"` would have removed that
check for **every** `_count` metric in the tree, and bought nothing: WHAT is
counted is already stated twice, by the metric name and by `AreaMetricSpec.what`.
The unit names the DIMENSION, never the thing counted.

Both halves of the reminder are enforced and tested: the record **carries** its
unit, and a record with no unit is **refused** (`NO_UNIT`), never assumed from
the name — `test_vacuous_a_record_with_NO_unit_is_refused_never_assumed`.

### F-4 / R5 — the three envelopes · **the CONSUMER moved**

`records_from_document` accepted one record, a bare list, or a
`metric_bundle.v1`, and **not one shipped producer writes any of the three**.
Measured on a real OpenROAD parse: the envelope holds **52 genuine records** and
the consumer indexed **0**.

**`_ppa/metrics.py` is the side that changed**, and the reason is structural
rather than a coin-toss: `bundle()` is built from a `MetricIndex`, and the index
**refuses a conflicting pair**. A producer forced to write a bundle could not
express "two artefacts disagree" *at all* — which is precisely what
`_ppa/backends/__init__.py` requires a backend to report. Making the producers
write bundles would have deleted the evidence between them.

New `M.RECORD_CARRIERS` maps envelope schema → the key its records live under.
An unregistered `vibeic.ppa.*` document is still **refused**, never read as empty
(rule 9). Measured after: `52 records -> OK 52`.

**Secondary, and it was real:** with every input unreadable the program still
wrote `{"records": []}` — byte-identical to a run that read a tree and found
nothing. The exit code was honest and the file was not. Now no bundle is written
when nothing was read, and a *partial* read writes a bundle that carries
`inputs_unreadable` so the file itself says what it could not open. The existing
test `test_vacuous_an_empty_directory_writes_no_bundle_that_reads_as_clean`
promised this in its name and its body admitted the opposite; it now asserts what
it says.

### F-9 / R7 — two readings of one metric under one scope · **I did NOT implement R7**

R7 asks for the source artefact to be put into `scope`. **I have not done that,
and I recommend against it.** It makes the collision go away by converting a
DETECTED conflict into two facts that quietly never compare again — the opposite
of what `_ppa/backends/__init__.py` requires ("A backend never resolves a
disagreement… ruling on the conflict is `_ppa/contract.py`'s job").

What I found instead is that **the index was calling agreement a conflict.**
Driving the backend over a real PnR directory:

| metric | openroad.log | openroad.metrics.json | before | after |
|---|---|---|---|---|
| `route.drc.violation.count` | **0** | **0** | `CONFLICTING_RECORD` | **corroboration, accepted** |
| `route.via.count` | 2502 | 2510 | `CONFLICTING_RECORD` | `CONFLICTING_RECORD` |
| `route.wirelength.um` | 12704.0 | 12722 | `CONFLICTING_RECORD` | `CONFLICTING_RECORD` |

The first row is two artefacts **confirming** a fact, and its refusal message
read "Two numbers claiming to be the same fact is a conflict" when the two
numbers were equal. One corroborated fact took down the whole record set.

`MetricIndex.add` now names four outcomes instead of two (contract §2.1):
byte-identical → `DUPLICATE_RECORD`; same status/unit/value from different bytes
→ **CORROBORATION**, kept once with the confirming artefact recorded in the
bundle's `corroborations`; different value → `CONFLICTING_RECORD`, and the
refusal now **names both source paths**; different value from the **same bytes**
→ `SAME_ARTEFACT_TWO_VALUES`, because identical bytes cannot support two numbers
and that is a parser defect, not a fact about the run.

Disagreement is still detected and still fatal to the claim. Records are left
byte-identical to what the producer parsed — corroboration lives in the index and
the bundle, not by rewriting parsed evidence.

### F-10 / R8 — every timing row emitted twice, and three slacks in one view

Two different defects, and the brief's dichotomy separates them exactly.

**(a) One reading read twice → the INPUT LIST was wrong.** `discover_reports`
de-duplicated on the *resolved path*, and the runner publishes each report into
two directories as separate files with identical bytes. Now it de-duplicates by
**content hash**, keeps the first in `_STA_DIRS` order, and each collapse is
reported as a note rather than dropped silently.

**(b) Three slacks under one scope → the SCOPE was wrong.**
`timing.*.worst_path_slack_ns` is emitted once per reported path and every one
carried the same scope. The scope now names the path: `path_startpoint` /
`path_endpoint` when the artefact gives them — an identity that is the same in
two runs of one design, so two arms stay comparable — and `path_ordinal` **only**
when it does not, since an ordinal moves if the tool reorders its output and a
cross-arm comparison over it should refuse. Never both.

Measured on the new specimen: 3 rows named by endpoints, 1 by ordinal, no two
rows from one artefact sharing a scope.

### F-2 — `--backend` drove no backend, including the ones that exist

All five shipped backends returned the same blanket rc=2. The CLI also had no
argument saying *what* to read.

`_ppa/backends/__init__.py` gains a driver seam: a backend that can turn one
path into records declares `extract_records()`; one that cannot declares
`NO_DRIVER_REASON`. Both are read by attribute, so teaching a backend to be
driven touches only that backend. `ppa_metric_extract.py` gains
`--backend TOOL --from PATH` (and `--stage` for the backend that needs it).

| backend | now |
|---|---|
| `openroad` | **drivable** — a run directory, a log, or a metrics JSON |
| `librelane` | **drivable** — see the caveat below |
| `yosys` | **drivable, requires `--stage`** — one transcript holds a generic and a mapped block; defaulting it compares a pre-techmap count against a mapped one |
| `opensta` | not drivable, **says why**: it produces a `Report`, and deciding what a slack MEANS is a domain rule |
| `orfs` | not drivable, **says why**: it parses AutoTuner rows the search layer holds, not an artefact on disk |

Measured end to end: `--backend openroad --from <run dir>` → 49 records indexed,
2 genuine conflicts refused, rc=1, no bundle. `--from <log>` → 35 records, rc=0,
bundle written.

**Also fixed here:** `RC_BAD_INVOCATION = 3` was defined in that file and never
used — `argparse` exits **2** on a usage error, which §1 reserves for "I could
not check". A typo and an unreadable input left a caller the same exit code. The
parser now exits 3, as §1 says.

### F-13 / R10 — which artefacts belong to `analysis`

The contract named five identities in a module-map line and never said what goes
in each, and the natural reading of "analysis artefacts" — the STA/DRC/LVS
reports — makes `ppa_problem_integrity_check` refuse **every** legitimate
comparison, because those files are outputs of the implementation.

**New contract §3.1** states the rule: *an artefact that varies with the
implementation may not sit in `analysis`.* `analysis` is the measurement
CONFIGURATION; it is never the reading.

**New finding `PPA-C-016`** makes it actionable. `PPA-C-012` is deliberately
unchanged — the comparison really is invalid — but when `analysis` differs **and
`implementation` differs**, the artefacts that moved are now named as misfiled,
with the rule and the fix. A bare digest mismatch sent the reader to diff two run
trees by hand.

The discriminator is tested too: `analysis` moving **alone** is a genuinely
different measurement (a moved corner) and must NOT be reported as misfiling.

§3.1 also records the F-14 hazard the E2E lane hit: a hash-based identity over an
emitted script is defeated by absolute host paths — emit it relative, or leave it
out of the identity **and say so**.

---

## The A/B, by TEST ID

Serial runs (`-p no:cacheprovider`, no `-n`), base measured in a **separate clean
worktree at `e36d81c0a`** so the two arms differ only by this branch.

**The PPA set** — `tests/test_ppa_*.py` + `test_readme_ppa_extractor.py` +
`test_issue1121_ppa_head_to_head.py` (39 files base, 41 after):

| arm | result |
|---|---|
| base `e36d81c0a` | **33 failed, 1085 passed** in 42.21s |
| this branch | **33 failed, 1123 passed** in 43.31s |

**The full affected surface** — every test file referencing `_ppa`,
`ppa_metric_extract`, `ppa_problem_integrity` or `PPA_INTERFACES` (47 base, 49
after):

| arm | result |
|---|---|
| base `e36d81c0a` | **35 failed, 1539 passed, 5 skipped, 2 xfailed** in 113.27s |
| this branch | **35 failed, 1577 passed, 5 skipped, 2 xfailed** in 113.54s |

**The failing TEST-ID sets are IDENTICAL on both arms — `comm` reports nothing in
either direction. No new failure, and no test that was red became green by
accident.** Both arms gain exactly **+38** passing tests, which is exactly the 38
this branch adds (13 + 13 + 3 + 6 + 3): 1085 -> 1123 and 1539 -> 1577.

### The 35 pre-existing reds are NOT mine, and here is what they are

| count | file | cause |
|---|---|---|
| 20 | `test_ppa_metrics_schema_agreement.py` | `jsonschema` |
| 12 | `test_ppa_contract.py` | `jsonschema` |
| 1 | `test_ppa_contract_fixtures.py` | `jsonschema` |
| 1 | `test_matrix_d2_falsifiable.py::test_d2_gate_has_a_reachable_fail[step1.6x]` | step 1.6x's one blocking clause reaches PASS on a deliberately-broken project |
| 1 | `test_not_verified_tier.py::test_no_new_undeclared_infrastructure_skip_appears` | `test_trusted_pytest_entry.py` carries an undeclared infrastructure-absent skip |

The `jsonschema` 33 are an **environment** fact with a real code defect behind
them, and it is worse than "not a declared dependency":

```
$ python3 -c "import jsonschema; print(jsonschema.__version__)"
3.2.0
E   AttributeError: module 'jsonschema' has no attribute 'Draft202012Validator'
```

`ppa_contract_check.py:118` guards `import jsonschema` and prints a correctly
worded `PPA-C-010` when it fails — but line 158 then uses
`jsonschema.Draft202012Validator` unconditionally. An **old but importable**
jsonschema walks straight past the guard and raises. The refusal is right; the
version check is missing. **Out of my items — reported, not fixed**, because
touching it would move my A/B baseline. See request 4.

---

## Mutation arms — every fix, reverted, with the test that goes red

Harness: revert one edit in place, run only the named test, restore. All ten went
red; a guard that cannot go red is not a guard.

| # | mutation | named test | verdict |
|---|---|---|---|
| 1 | `area.py` declares `"cells"` again | `..._agreement.py::test_every_area_metric_builds_a_record_its_own_consumer_ACCEPTS` | **RED** rc=1 |
| 2 | `RECORD_CARRIERS` holds only the bundle | `..._agreement.py::test_the_three_shipped_producers_write_documents_the_consumer_READS` | **RED** rc=1 |
| 3 | agreement called a conflict again | `..._second_record_identity.py::test_two_artefacts_that_AGREE_are_corroboration_not_conflict` | **RED** rc=1 |
| 4 | conflict detection removed | `..._second_record_identity.py::test_two_artefacts_that_DISAGREE_are_still_refused` | **RED** rc=1 |
| 5 | dedupe by resolved path again | `test_ppa_timing.py::test_a_report_published_into_two_directories_is_read_ONCE` | **RED** rc=1 |
| 6 | path identity dropped from scope | `test_ppa_timing.py::test_every_reported_path_row_says_WHICH_path` | **RED** rc=1 |
| 7 | openroad's driver removed | `test_ppa_metrics_extract_cli.py::test_the_backend_seam_actually_EXTRACTS` | **RED** rc=1 |
| 8 | the blanket backend refusal returns | `test_ppa_metrics_extract_cli.py::test_the_backend_seam_actually_EXTRACTS` | **RED** rc=1 |
| 9 | the misfiling diagnosis removed | `test_ppa_problem_integrity.py::test_a_report_declared_under_analysis_is_named_as_MISFILED` | **RED** rc=1 |
| 10 | an empty bundle is written again | `test_ppa_metrics_extract_cli.py::test_vacuous_an_empty_directory_writes_no_bundle_that_reads_as_clean` | **RED** rc=1 |

**Arm 4 is the one that matters most for F-9.** It proves the corroboration
change did not quietly disable conflict detection: force `_states_the_same_fact`
to always-true and the DISAGREE test goes red.

**Two arms I had to strengthen after they failed to go red, recorded because the
first version would have shipped a guard that guarded nothing:**

* my first F-2 guard asserted only that *some* backend is drivable — disabling
  openroad's driver left librelane and yosys and it stayed **green**. Replaced
  with an end-to-end guard through the process: `--backend openroad --from <log>`
  must exit 0 and index a record with the value the log states.
* my first path-identity test ran on a fixture with **one** path row, so "no two
  rows share a scope" was satisfied by having nothing to collide with. Added a
  specimen with three paths in one view, and asserted `len(path_rows) >= 4` and
  the exact value set so it cannot go vacuous again.

### Non-vacuity, checked rather than assumed

* the envelope census asserts it scanned `> 10` schemas before concluding;
* every registry-walking test asserts its registry is non-empty first;
* the path-identity test exercises **both** naming branches — measured 3 named,
  1 ordinal;
* `test_the_unit_rule_is_ENFORCED_and_not_merely_declared` re-applies the exact
  pre-v1.11.33 declaration and requires `UNIT_CONTRADICTS_NAME`, so the census
  cannot pass over a tree where the enforcer stopped firing.

**The census found a defect I had missed by hand.** It failed on first run naming
`vibeic.ppa.area_verdict.v1`, an envelope I had not seen in the findings. It is
an adjudication and not a record carrier, so it is classified as such — but that
is the census doing the job it was written for on its first execution.

---

## What I could NOT settle

**1. `librelane` produces records the canonical consumer refuses — a FOURTH
producer, and worse than the three.** F-4 named three; there are four. Measured:

```
design__instance__area   MEASURED -> ['BAD_METRIC_NAME', 'SCOPE_INCOMPLETE', 'NO_UNIT']
design__instance__count  MEASURED -> ['BAD_METRIC_NAME', 'SCOPE_INCOMPLETE', 'NO_UNIT']
timing__setup__ws        MEASURED -> ['BAD_METRIC_NAME', 'SCOPE_INCOMPLETE', 'NO_UNIT']
```

Its rows are invalid at the **record** level, not just wrapped in an unreadable
envelope: LibreLane's `design__instance__area` is not a canonical dotted name,
no row carries a `stage`, and **no row carries a `unit` at all**. I did **not**
fix it. Mapping those keys onto canonical names and units needs evidence for
each unit that I do not have here, and inventing them is the exact defect
`openroad.py` refuses by name ("It does not map a `-metrics` JSON key whose unit
it could not establish from evidence"). I drove it anyway rather than hiding it,
and said so in the driver's docstring, so the gap is loud instead of silent.

**2. The `timing_rows.v1` schema edit is additive, and §5 says v1 is never
edited.** Naming the path in scope needs three optional properties, and the
scope block is `additionalProperties: false` — which I kept, so an *undeclared*
scope key is still refused. Every document valid under the old schema stays valid
under the new one, and nothing hashes against the schema file (records carry
`vibeic.ppa.metric.v1`; the envelope hashes rows, not the schema). I judged that
§5's precondition — "once something has **hashed against it**" — is not met, and
that minting `timing_rows.v2` for three optional keys would ripple through the
producer, `RECORD_CARRIERS` and every consumer for no gain. **If the lander reads
§5 more strictly, the zero-schema-change alternative is R8's other option: emit
only the worst path per (clock, check) and drop the rest.** That needs no schema
edit; it discards the 2nd/3rd-worst paths, which is why I did not choose it.

**3. I could not reproduce the E2E lane's run tree.** Everything above is
measured against synthetic specimens transcribed from the real logs already in
`tests/`, plus a faithful OpenROAD run directory I built from
`LOG_MODERN` + a metrics JSON that disagrees in the direction the module
docstring records as measured. The 61-arm `spm` tree is not on this host, so the
F-13 numbers I quote are the E2E lane's, not re-measured by me; the F-13 *rule*
is re-proved here on the contract fixtures instead.

**4. `--backend` still cannot drive `opensta` or `orfs`,** and I did not force
it. Both now state their own reason. Wiring opensta would mean a second
implementation of `_ppa/timing.py`'s view rules inside a parser, free to disagree
with the first about one number.
>>>>>>> origin/jrecords/record-shape-reconcile

---

## REQUESTS TO THE LANDER

<<<<<<< HEAD
### A. Fixes in other lanes' files that I wrote the test for but did not make

Each is currently `xfail(strict=True)`; landing the fix turns the pin red and it
must then be deleted. Ordered by blast radius.

1. **F-11 — feasibility lane, `_ppa/feasibility.py`.** `required_views` must be
   scoped per axis (or per proof, or a view must declare which axes it binds).
   Today the hard promotion gate cannot return FEASIBLE for any candidate whose
   contract declares more than one view class. **9 of 9 axes UNDETERMINED** on a
   clean, fully-measured candidate. Test:
   `test_ppa_layer_feasibility_view_scope.py` (3 pins).

2. **F-4 — record-envelope lane, `_ppa/power.py` + `_ppa/timing.py` +
   `_ppa/metrics.py`.** Producers and the canonical consumer disagree about the
   shared shape. **48/48 power records** and **every timing row** are refused;
   `MetricIndex.add` raises on a real STA row. Either producers stop writing
   `None` scope fields (or record them as declared absences) or `validate`
   accepts one — your call, either turns the tests green. Test:
   `test_ppa_layer_producer_consumer.py` (10 pins).

3. **F-5 — record-envelope lane, `_ppa/area.py`.** Three metrics declare a unit
   the metric name refuses: `cells`/`wires`/`wire_bits` vs `count`. Included in
   the 10 pins above.

4. **F-10 — `_ppa/timing.py`.** `discover_reports` must de-duplicate by artefact
   **content** (`source.sha256`), not by resolved path. Test:
   `test_ppa_layer_timing_view_dedup.py` (2 pins).

5. **F-2 — whichever lane owns the extractor seam.** `ppa_metric_extract
   --backend` must drive the five modules in `_ppa/backends/`. Test:
   `test_ppa_layer_backend_seam.py` (5 pins). Two arms that must stay green are
   included, because the tempting wrong fix is "return 0 and write an empty
   bundle".

6. **Search lane, `ppa_search_run.py` — two, both one-liners.**
   * `--this-flag-does-not-exist` exits **2**; §1 says 3. `_ppa/cli_exit.py` ships
     in this branch and is the drop-in.
   * a space document declaring **no lever** returns **rc=0** with an invented
     `budget 1 trial(s) / 1 full-PnR: proposed 1`. Should be rc=2 `[CANNOT
     CHECK]`. Note the module docstring's *"`Budget()` with no arguments is
     `max_trials=1`"* is a defensible **module** decision; this is the **CLI**
     reporting PASS over an empty population.
   Tests: `…exit_contract` (1 pin), `…vacuous_population` (1 pin).

7. **Feasibility lane, `ppa_feasibility_check.py` + `ppa_pareto_check.py`.**
   `--help` exits **3**. Their `except SystemExit: return RC_BAD_INVOCATION` needs
   to read `exc.code`; `_ppa/cli_exit.parse_or_refuse` is exactly that.
   Test: `…exit_contract` (2 pins).

### B. Generated files — NOT regenerated, per §6 and your constraint

`PROGRAM_INVENTORY.json` is stale on this branch: **`test_files` 2685 → 2692**
(7 new test files; `programs_top_level` is unchanged at 1223 because
`_ppa/cli_exit.py` is not top-level and `_ppa_jsonschema.py` is under `tests/`).

`gen_program_inventory.py --check` is **already rc=1 on pristine base with 30
problems**, and its output is **byte-identical on base and on this branch**:

```
$ diff <(base: gen_program_inventory.py --check | sort) <(branch: … | sort)
  (no output)
```

so this branch adds nothing to that gate. Please regenerate on the merged tree
and take the generator's output rather than merging either side.

### C. Protected paths — none touched

```
$ python3 -c "<intersect git status --porcelain with protected_landing_transition.json>"
  protected paths in manifest: 48
  files I changed: 26
  INTERSECTION (protected paths I touched): NONE
```

`tools/ci/repo_hygiene_gates.sh` is untouched, so **no manifest re-render is
needed** and I have no sha256 to hand you.

### D. Two things worth a follow-up lane

* the §1 **stream discipline** sweep (§6) — human summary on stdout, refusals on
  stderr, across all 14 programs. I measured one violation and did not sweep.
* an **unguarded `import yaml`** in two PPA test files (§6).
>>>>>>> origin/agent/jppa-tests
=======
**1 — `tools/ci/protected_landing_transition.json`: no change needed.** I
checked all 47 pinned paths against my diff: none of the 19 files this branch
touches is protected. No manifest re-render is required for this branch.

**2 — Please confirm the `timing_rows.v1` schema call** (What I could not settle,
2). Additive optional properties, `additionalProperties: false` retained. Say the
word and I will convert it to R8's emit-only-the-worst form, which needs no
schema change at all.

**3 — `_ppa/backends/librelane.py` needs an owner decision** (What I could not
settle, 1). Every MEASURED row it emits is refused three ways. It needs a
key→(canonical name, unit, stage) map like `openroad._JSON_MAP`, and each unit
needs evidence. Until then it is a backend that can be driven and whose output
the assembler refuses — which is honest, and useless.

**4 — `ppa_contract_check.py` needs a jsonschema VERSION check, not just an
import check.** Line 118 guards the import; line 158 uses
`Draft202012Validator` unconditionally. With `jsonschema 3.2.0` installed the
`PPA-C-010` refusal never fires and the program raises `AttributeError` instead.
That is 33 of the 35 reds on clean main on this host. Fix is a version guard
folded into the existing `PPA-C-010` branch. Out of my items, so untouched.

**5 — `_ppa/metrics.py` still has no `metric_bundle.v1` schema file**, and its
own comment raises this as a request to you. §5 says every instance document has
one; `schemas/ppa/` has no `metric_bundle`. My `RECORD_CARRIERS` census would
cover it the day it lands.

**6 — Two pre-existing reds on clean main are unrelated to this branch** and
belong to whoever owns them: `step 1.6x`'s only blocking clause reaches PASS on a
deliberately-broken project (`test_matrix_d2_falsifiable.py`), and
`test_trusted_pytest_entry.py` carries an undeclared infrastructure-absent skip
(`test_not_verified_tier.py`).

**7 — R7 was deliberately not implemented as written** (F-9 above). If you want
the artefact in `scope` after all, it should be a declared authority-order
resolution in `_ppa/contract.py` rather than a scope key, so the override is
named and printed as `PPA-C-015` instead of two facts silently ceasing to
compare.

---

## Files

```
docs/PPA_INTERFACES.md                      §2 unit rule, §2.1 second record, §3.1 identities
schemas/ppa/timing_rows.v1.schema.json      three optional path-identity scope keys
programs/_ppa/area.py                       F-5: three units, "cells"/"wires"/"wire_bits" -> "count"
programs/_ppa/metrics.py                    F-4 RECORD_CARRIERS; F-9 corroboration vs conflict
programs/_ppa/timing.py                     F-10a content-hash dedupe; F-10b path identity in scope
programs/_ppa/contract.py                   PPA-C-016 registered
programs/_ppa/backends/__init__.py          F-2 the driver seam
programs/_ppa/backends/openroad.py          F-2 driver
programs/_ppa/backends/librelane.py         F-2 driver (+ its refusal caveat, written down)
programs/_ppa/backends/yosys.py             F-2 driver, requires --stage
programs/_ppa/backends/opensta.py           F-2 NO_DRIVER_REASON
programs/_ppa/backends/orfs.py              F-2 NO_DRIVER_REASON
programs/ppa_metric_extract.py              F-2 --backend/--from; F-4 secondary; §1 rc=3
programs/ppa_problem_integrity_check.py     F-13 PPA-C-016 diagnosis
programs/tests/test_ppa_producer_consumer_agreement.py   NEW, 13 tests (F-4, F-5, F-2 census)
programs/tests/test_ppa_second_record_identity.py        NEW, 13 tests (F-9, §2.1)
programs/tests/test_ppa_timing.py           +3 (F-10a, F-10b)
programs/tests/test_ppa_metrics_extract_cli.py  +6 (F-2 end-to-end, F-4 secondary)
programs/tests/test_ppa_problem_integrity.py    +3 (F-13 negative/positive/discriminator)
```

No GDS was hand-edited, no geometry deleted, no pin moved, no rule deck relaxed.
No `--write-baseline` was run on any hygiene gate. No plugin version was bumped.
>>>>>>> origin/jrecords/record-shape-reconcile
