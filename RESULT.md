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
