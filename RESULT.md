# The 63x8 matrix family on main: 54 red test IDs, driven to 12

Branch `jmatrix/63x8-main-reds`, six commits, now rebased onto `origin/main`
`e36d81c0a` (v1.11.33). The 54 were measured at `867de4289` (v1.11.18) and are
re-measured here on both bases.

**42 of the 54 are green. 12 remain, and they now form one dependency graph
rather than a list.**

## Base: rebased onto v1.11.51. The lane's code has LANDED.

This lane landed as v1.11.44. What is left here is the record plus one repair the
merge itself needed. Rebased across three bases as main moved under it —
v1.11.33 -> v1.11.47 -> v1.11.51 — and re-measured on each, by TEST ID, serially.

| base | the 54: red | green |
|---|---|---|
| `867de4289` v1.11.18, bare | 53 | 1 |
| v1.11.33, this lane | 12 | 42 |
| v1.11.47, this lane | 14 | 40 |
| **v1.11.51, this lane** | **11** | **43** |

`git diff --stat origin/main..HEAD` is 5 files — lane-sized, as the sanity check
requires.

**Two moved between v1.11.33 and v1.11.51 and both are worth naming.**

`test_d7_required_outputs_list_is_complete[step31]` **CLOSED**, and not by me. It
was the one bucket-B item I named and declined to fix, because I measured the
knock-on: *"adding a `required_outputs` entry moves `required_output_entries`
162 -> 163 and `FILE` 120 -> 121"*. Another lane declared
`reports/phase3/drc_signoff.json` on step 31, the red closed, and the predicted
knock-on happened exactly as stated.

Three went RED at v1.11.47 and are closed again here: the entries pin and the two
census-freshness IDs. **The census block went stale AGAIN, inside one batch.**
That is the third recurrence of the failure §3 is about, and it happened while
this branch was in flight.

### The shared pin, re-derived rather than added up

`test_output_entries_classify_into_the_four_kinds` is the constant two lanes
moved. The landed note pinned **163/121**; the live tree answered **164/122**.
Neither lane's number was right, because a third entry had landed after both
notes were written. Re-derived on the merged tree and attributed by measurement —
diffing the (step, entry) SET between the v1.11.18 yaml and this tree gives
exactly two additions and no removals:

    +1  1.6x    reports/crosslayer/rewrite_equivalence_check.json   (this lane)
    +1  15.5ic  reports/phase3/pad_assignment.json                  (cpath)
    +1  31      reports/phase3/drc_signoff.json                     (the d7 fix)

### The attribution dispute is SETTLED, and both lanes were right

The merged note recorded that two lanes attributed "the first +1" differently —
one to 1.6x, one to the 37.5self/37.5ic swap — and left it open. Driving
`flowref` at each revision's yaml through `VIBE_IC_MATRIX_FLOW_YAML`:

| yaml at | steps | entries | FILE | 1.6x | 37.5self |
|---|---|---|---|---|---|
| `ff5071caa` | 68 | 154 | 114 | no | no |
| `7fcbc7397~1` | 69 | 160 | 118 | no | **yes** |
| `7fcbc7397` | 70 | **161** | **119** | **arrives** | yes |
| `867de4289` | 69 | **162** | **120** | yes | **retired** |

There are **two** +1s in that span, one per commit. `7fcbc7397` moved 160 -> 161
and that is step 1.6x; `867de4289` moved 161 -> 162 and that is the swap.
Neither lane was wrong — each attributed the increment it had measured, and the
disagreement was that both were describing "the first" when there were two.

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

---

## MEASURED ON MAIN v1.11.57, WITH THE NINTH DIMENSION LANDED

The previous section measured this on a branch because the ninth dimension was
not yet in the tree. It is now (`e4c5840d6`, v1.11.57), so both questions are
re-answered against main itself. The branch and main agree to the cell, which is
the independent confirmation that the merge landed coherently.

The corrected anchor is visible on main: `flowref.py` reads
`621<!--figure:ledger_cells-->`. My branch said 552 because it predated the ninth
dimension. Neither side was merged; the generator re-derived it on the merged
tree and `--check` reports no change. That is the rule working, and it is the
same rule that decided the entries pin (163 vs 162, tree said 164) and the d8
gradability reading.

### The 69 x 9, verified fresh by the repository's own gate

```
$ python3 tools/gen_matrix_63x8_census.py . --check      # on origin/main e4c5840d6
[PASS] 63x8 derived figures fresh: 57 anchored figure(s) re-derived across 35 corpus files.
[PASS] 63x8 census fresh: 621 cells over 9 dimensions; ENFORCED own=19
       substituted=117 undeclared=403; CONTRADICTED=6 NOT-MEASURED=49
       WAIVED=8 NA=19 (621/621 accounted).
```

**Every one of the 621 cells is in a NAMED state.** Two independent partitions
each total 621, so nothing is unaccounted on either axis:

* outcome axis: 19 + 117 + 403 + 6 + 49 + 8 + 19 = 621
* state axis: 539 ENFORCED + 6 CONTRADICTED + 8 WAIVED + 19 NA
  + 46 ENFORCED-SKIPPED + 3 WAIVED-SKIPPED = 621

**19 cells are measured against the step's OWN mechanism. 602 carry a gap with a
written reason.**

| | cells | the written reason |
|---|---:|---|
| ENFORCED, own mechanism | **19** | — the floor, and the only figure that means "enforcing" plainly |
| ENFORCED, substituted | 117 | runs against a stand-in; each carries a disclosure from the owning module |
| ENFORCED, undeclared | 403 | the dimension has not answered the question; UNDECLARED is a state, not a synonym for clean |
| NOT MEASURED | 49 | the predicate declined and NAMED the resource it could not reach |
| NA | 19 | dormant, guarded by a live precondition that self-invalidates |
| WAIVED | 8 | the accepted-gap registry, which requires a reason AND evidence |
| CONTRADICTED | 6 | configured enforcing while its own predicate is RED — a disclosed defect |

**3.1% own-mechanism, 96.9% disclosed gap.** That is the campaign's own answer,
and it is why the census refuses to publish a single "enforcing" total.

**The ninth dimension arrives own=1, substituted=68.** `verdict_consumed` asks a
real question — when a step FAILs, does the verdict reach the exit code — and on
this tree answers it through a stand-in for 68 of 69 steps. It has started, not
finished. If it is read as an enforcing dimension, that is 68 cells of credit
nobody has evidence for.

## THE d8 BLOCKER: ANSWERED, AND THE SEVEN ARE MOSTLY RELEASED

Re-verified on today's tree (v1.11.51) rather than restated.

**(a) It was a real finding, not a stale pin — and it is now closed.** The
measurement that settled it: seeding step 1.6x's one declared output with wrong
content and running its own gate command gave sha256 `02998b14…` before and
`22bad440…` after. The gate OVERWROTE it. `_gradable` was deciding "is there a
content channel" from the filename SUFFIX, and a `.json` passed — but a declared
output that is the gate's own `--json` destination carries nothing into the
verdict. Four steps are in that position (`1.6x`, `2`, `8`, `36`). The fix
implemented the rule this file already stated; it did not relax it. Landed
v1.11.44.

**(b) The NORECORD rule is CORRECT, and the evidence is what happened when the
eighth red was fixed.** The census is a claim about the whole grid derived from
one nested session's rc; a session red for a reason no cell represents makes that
claim false. It is guarded in both directions by
`test_a_red_non_cell_helper_cannot_represent_the_nested_session_rc`, which
passes. It was not touched — and fixing the eighth released the others, which is
exactly how a correct rule behaves. A rule that had been over-broad would have
kept them blocked.

**Measured on MAIN v1.11.57: 5 of the 7 are GREEN, 2 red.** Same verdict as on
the branch, and the d8 one is among the green.

```
test_the_census_block_is_fresh                                GREEN
test_the_published_total_equals_the_live_census               GREEN
test_every_cell_has_a_live_outcome_and_the_outcome_run_...    GREEN
test_the_enforcement_census_is_reported_for_humans            GREEN
test_a_readable_artefact_that_is_wrong_...                    GREEN
test_every_na_cell_asserts_a_live_precondition                RED
test_no_cell_is_counted_enforced_while_its_predicate_is_red   RED
```

The two still red are **no longer NORECORD-blocked**. They are red on their own
content, and they name their cause exactly:

> 55 of **621** cells are reported in a state their own live predicate
> contradicts (6 measured red, 49 not measured). MEASURED RED — these are repo
> defects: 15/d3, 17/d3, 19/d3, 20/d3, 30/d3, 32/d3.

The same 55 against a larger denominator: **the ninth dimension added no
contradicted and no not-measured cell.** All nine of its cells per step are
accounted, 68 of them substituted.

And the OTHER of the two is a DISTINCT finding, separated here for the first
time — it is not part of the d3 aggregate:

> 2 NA problem(s): dimension 3 `test_d3_required_outputs_are_produced`
> `pytest.skip()` at line 2309; dimension 7
> `test_d7_required_outputs_list_is_complete` `pytest.skip()` at line 375.
> A cell test may not skip: the three states are ENFORCED, WAIVED (strict
> xfail) and NA (asserted precondition).

That is a matrix-contract violation, not a corpus problem: a cell test that
skips has left the three-state partition the whole grid is built on. Closing it
means converting each skip into an ASSERTED NA precondition — which is real work
and is NOT done here, because doing it by widening what counts as NA is exactly
the relaxation this file refuses.

Those six ARE the six `test_d3_required_outputs_are_produced[stepNN]` IDs already
on this list. So `test_no_cell_is_counted_enforced_while_its_predicate_is_red` is
their AGGREGATE, not a ninth finding — the honest count of open *defects* behind
the 11 remaining IDs is **7**: six d3 manifest citations plus the two
mutation-ledger cells (1.6x/d3, 0.5ic/d3) whose mutation is ALREADY_RED at
baseline.

## THE 69 x 9, MEASURED — what "the matrix is done" would mean

The ninth dimension is **not on main** (`git grep test_matrix_d9_verdict_consumed
origin/main` -> 0); it is on `jm9/d9-verdict-consumed`, rebased onto v1.11.51.
Measured there, and verified fresh by the repository's own gate rather than read
off the block:

```
$ python3 tools/gen_matrix_63x8_census.py . --check
[PASS] 63x8 derived figures fresh: 60 anchored figure(s) re-derived across 35 corpus files.
[PASS] 63x8 census fresh: 621 cells over 9 dimensions; ENFORCED own=19
       substituted=117 undeclared=403; CONTRADICTED=6 NOT-MEASURED=49
       WAIVED=8 NA=19 (621/621 accounted).
```

**Every one of the 621 cells is in a named state.** Both partitions total 621
independently — the outcome axis (19+117+403+6+49+8+19) and the state axis
(539 ENFORCED + 6 CONTRADICTED + 8 WAIVED + 19 NA + 46 ENFORCED-SKIPPED +
3 WAIVED-SKIPPED). Nothing is unaccounted.

**19 cells are measured against the step's OWN mechanism. 602 carry a gap with a
stated reason.**

| | cells | the reason it is a gap |
|---|---:|---|
| ENFORCED, own mechanism | **19** | — this is the floor, and the only figure that means "enforcing" in the plain sense |
| ENFORCED, substituted | 117 | the predicate runs against a stand-in; each carries a disclosure from the module that owns it |
| ENFORCED, undeclared | 403 | the dimension has not answered the question at all; UNDECLARED is a state, not a synonym for clean |
| NOT MEASURED | 49 | the predicate declined and named the resource it could not reach |
| NA | 19 | dormant, and the dormancy is guarded by a live precondition that self-invalidates |
| WAIVED | 8 | the accepted-gap registry, which requires a reason AND evidence |
| CONTRADICTED | 6 | configured enforcing while its own predicate is RED — a disclosed defect |

So **3.1% of the grid is measured against its own mechanism** and 96.9% is a
disclosed gap. That is not a failure of the campaign; it is the campaign's own
answer to the question, and the reason the census refuses to publish a single
"enforcing" total.

**The ninth dimension arrives almost entirely substituted**: `verdict_consumed`
is own=1, substituted=68. It asks a real question — when a step FAILs, does the
verdict reach the exit code — and on this tree it answers it through a stand-in
for 68 of 69 steps. Read it as a dimension that has started, not one that is
done.

---

## THE d8 QUESTION, ANSWERED A THIRD TIME — SAME ANSWER, NOW ON v1.11.62

Re-measured on bare `origin/main` `6dfe15a32`, not restated. The answer has been
stable across three bases (v1.11.51, v1.11.57, v1.11.62).

**(a) It was a real finding, and it is CLOSED.** The measurement that settled it:
seeding step 1.6x's one declared output with wrong content and running its own
gate gave sha256 `02998b14…` before, `22bad440…` after — the gate OVERWROTE it.
`_gradable` was deciding "is there a content channel" from the filename SUFFIX,
and a `.json` passed even when the gate's own `--json` destination was the only
candidate. Four steps sit in that position (`1.6x`, `2`, `8`, `36`). The fix
implemented the rule the file already stated. It landed at v1.11.44 and
`test_a_readable_artefact_that_is_wrong_...` is **GREEN on main today**.

**(b) NORECORD-while-any-red-sits-outside-the-join is the RIGHT rule, and it was
not relaxed.** The census is a claim about the whole grid derived from ONE nested
session's rc; a session red for a reason no cell represents makes that claim
false. It is guarded in both directions by
`test_a_red_non_cell_helper_cannot_represent_the_nested_session_rc`, which
passes. The behavioural proof that it is not over-broad: fixing the eighth red
RELEASED the others. An over-broad rule would have kept them blocked.

**Measured on v1.11.62 — 5 of the 7 are GREEN, 2 red:**

```
test_the_census_block_is_fresh                                GREEN
test_the_published_total_equals_the_live_census               GREEN
test_every_cell_has_a_live_outcome_and_the_outcome_run_...    GREEN
test_the_enforcement_census_is_reported_for_humans            GREEN
test_a_readable_artefact_that_is_wrong_...                    GREEN   <- the d8
test_every_na_cell_asserts_a_live_precondition                RED
test_no_cell_is_counted_enforced_while_its_predicate_is_red   RED
```

The two remaining are **not NORECORD-blocked and are not one finding**. Nothing
here is left blocked by the rule.

## THE ELEVEN, OWNED — reason, owner, expiry

`origin/main` v1.11.62 measures **11 of the original 54 red**, and they are three
root causes, not eleven. Rows in the shape the persistent-red deadline asks for.

### RED-63X8-1 — six d3 cells cite a run root no corpus can supply

* **IDs (7):** `test_d3_required_outputs_are_produced[step15|17|19|20|30|32]`,
  and `test_no_cell_is_counted_enforced_while_its_predicate_is_red`, which is
  their AGGREGATE — it names exactly those six and nothing else
  ("55 of 621 cells ... MEASURED RED: 15/d3, 17/d3, 19/d3, 20/d3, 30/d3, 32/d3").
* **Reason:** the dimension-3 manifest cites a `home`-kind campaign run root.
  The module searches `published` and `repo` roots on every host and this one on
  none, so setting `VIBE_IC_BENCHMARK_DATA` does not help. The test refuses to
  let the corpus-absent skip cover it, which is correct: it is NOT DETERMINED,
  not clean.
* **NOT INHERITED FROM MY WORK, measured:** the citation appears 7 times in the
  manifest both before and after `7fcbc7397`, so it predates the 1.6x family
  entirely.
* **Owner:** unclaimed. I will take it as matrix-substrate owner if nobody
  else does, but the closing move is not mine to make alone.
* **Closes when** any ONE of: the six records are re-pointed at a root that
  carries the artefact; a run tree carrying them is published; or the cells are
  waived through the one registry with the disclosure. **Never by widening the
  skip** — the test says so and it is right.
* **Expiry: 2026-09-30.** Long because two of the three closures need a
  published run, which is not on my side of the fence.

### RED-63X8-2 — the state grid has four states and the NA contract enumerates three

* **ID (1):** `test_every_na_cell_asserts_a_live_precondition`
* **Reason, and this is a FINDING rather than a defect to patch:** it fails with
  *"A cell test may not skip: the three states are ENFORCED, WAIVED (strict
  xfail) and NA (asserted precondition)"*, naming `test_d3_required_outputs_are
  _produced` (line 2309) and `test_d7_required_outputs_list_is_complete`
  (line 375). Both skips are deliberate and well-argued: d3's fires only when
  there is no run root AND no corpus, after REFUSING the unanswerable citations
  by name; d7's only when a waived cell has nothing to show, the observed half
  observed nothing, and there is no corpus. Both are the repository's own
  doctrine — a check that cannot measure must not report that it measured.
* **The conflict is real and it is in the CONTRACT, not the skips.** The census
  beside this test publishes a FOURTH state — `NOT MEASURED`, 49 cells,
  *"a predicate that declined to run, naming a resource it could not reach ...
  read them as UNKNOWN, never as coverage"* — and these skips are how cells
  enter it. So the grid has four states and this test's enumeration has three.
* **What I did NOT do:** widen the test to accept the corpus skip. That would
  close this red and two others, and it is a decision about what the state grid
  IS. Making it to harvest greens is exactly the move this file refuses.
* **Owner:** matrix substrate (me), pending the owner's ruling on whether
  `NOT MEASURED` is a first-class cell state.
* **Closes when** either the two skips become asserted NA preconditions, or the
  contract admits `NOT MEASURED` as the fourth state with the same disclosure
  discipline the census already applies to it.
* **Expiry: 2026-09-05.** Short: it needs a ruling, not a run.

### RED-63X8-3 — two ENFORCED cells whose mutation is ALREADY_RED at baseline

* **IDs (3):** `test_every_enforced_cell_carries_a_named_mutation[step1.6x]`,
  `[step0.5ic]`, and `test_the_coverage_is_complete_and_the_count_is_stated`,
  which counts them.
* **Reason:** `1.6x/d3` and `0.5ic/d3` are ENFORCED, so the ledger requires a
  measured mutation. `--replay D3-UNDECLARED-ARTEFACT --step 1.6x` is
  `NOT_REPLAYABLE` with no corpus (the witness skips) and `ALREADY_RED` with one
  (`baseline_rc=1` — the step's declared output exists in no published run). A
  mutation cannot be measured on a cell that is red before the edit, and the
  ledger's own vocabulary says so.
* **Coupled to RED-63X8-1:** both cells are d3, and the same missing published
  evidence is why the baseline is red. Closing 1 very likely closes this.
* **Owner:** matrix substrate (me).
* **Closes when** the d3 baseline for those two steps is green — i.e. when
  RED-63X8-1 closes — and the twelve-entry replay is extended to them.
* **Expiry: 2026-09-30**, tracking RED-63X8-1.

**None of the three is closed by relaxing anything, and none is blocked by the
NORECORD rule.** Two need evidence this repository does not hold; one needs a
ruling on how many states the grid has.
