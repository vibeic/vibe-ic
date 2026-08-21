# j63b — the remaining 63x8 reds, re-enumerated, classified and three of them closed

Measured tree: `origin/main` @ `a00f53f20` [v1.11.66] — RE-FETCHED at the end
of this work and still the head, so nothing here is measured against a main that
has since moved. Fresh `git worktree`,
`PYTHONDONTWRITEBYTECODE=1`, corpus pointer UNSET, one pytest process per file.
Host load recorded per run, because four of the seventeen turn on it.

## HEADLINE, stated first because the brief asked for it loudly

**There is no d8 red. Dimension 8 is 347 passed / 0 failed, rc=0, twice.**
The structure the campaign was routing around — "seven are stuck behind ONE d8
red" — does not exist on this commit. `test_matrix_d8_missing_caught.py` is
entirely green in 83.11 s in the sweep and 34.73 s alone. Nothing is waiting on
it. Whatever the seven were when they were counted, dimension 8 is not what
holds them.

## The live red set: 17, and where it was hiding

The first sweep over the 19 `test_matrix_*.py` files found 15. The family is
wider than that prefix: ten more files consume the same census or the same
dimension-3 evidence manifest, and one of them carried the other two reds.
Ranking candidate files by real coupling (an import of `matrix_63x8` /
`matrix_cell_state` / `gen_matrix_63x8_census`, not a mention in a comment)
is what surfaced them.

| # | id | which of the three | what was done |
|---|----|--------------------|---------------|
| 1-6 | `d3_outputs_produced::test_d3_required_outputs_are_produced[15,17,19,20,30,32]` | NOT_MEASURED (evidence) | VERIFIED absent, see below. Owned by `jfindings-63x8` |
| 7-9 | `matrix_mutation_ledger` — `[0.5ic]`, `[1.6x]`, `coverage_is_complete` | NOT_MEASURED | reason recorded below; closes with the fourth-state ruling |
| 10 | `63x8_coverage::..._relays_finite_semantic_progress_past_old_bound` | NOT_MEASURED (quiet host) | PASSES in the full-file run at load 3.45 |
| 11 | `63x8_coverage::..._chatty_import_without_events_fails_closed` | NOT_MEASURED (quiet host) | PASSES in the full-file run at load 3.45 |
| 12 | `63x8_coverage::..._nested_outcome_run_outlives_old_fixed_bound...` | **REAL FINDING — FIXED** | zero margin by construction; fixed + negative control added |
| 13 | `63x8_census_freshness::test_the_census_block_is_fresh` | NOT_MEASURED (quiet host) | `1 passed in 163.79s` alone |
| 14 | `63x8_coverage::test_every_na_cell_asserts_a_live_precondition` | REAL FINDING | already fixed on `jfindings-63x8`'s branch; not duplicated |
| 15 | `63x8_coverage::test_no_cell_is_counted_enforced_while_its_predicate_is_red` | THE RULING | 55 of 621 cells: 6 measured red, 49 not measured |
| 16 | `flow_manifest_declaration_parity::test_every_declared_path_has_a_manifest_entry` | **STALE PIN — FIXED** | re-derived on the current tree |
| 17 | `flow_manifest_declaration_parity::test_the_population_is_the_whole_flow_and_is_not_empty` | **STALE PIN — FIXED** | same cause as 16 |

Green in the same sweep: d1 82, d2 85+2xf, d4 77, d5 81+1xf, d6 81+1xf,
d7 97+3s+4xf, **d8 347**, d9 80, 63x8_ledger 52, figure_coverage 12,
waiver_single_source 4, write_record_scope 7, a3, a8,
artefact_mutation_channel, and the eight further census consumers.

## Why this reports on NINE and not the brief's fourteen

The brief allocated "the other fourteen" by arithmetic: 17 remaining, minus the
three findings `jfindings-63x8` named, leaves 14. That subtraction treats a
FINDING as a RED, and here it is not. Its three findings span seven reds:

* **two needing evidence** — the d3 unanswerable citations, which is ONE cause
  with SIX parametrized ids (steps 15, 17, 19, 20, 30, 32) across two cited run
  roots;
* **one needing a ruling** — `test_no_cell_is_counted_enforced_while_its_
  predicate_is_red`, one red.

Plus `test_every_na_cell_asserts_a_live_precondition`, which is already fixed on
that branch and so is not among its three REMAINING findings, but is equally not
work to redo here. That is eight reds accounted for elsewhere and **nine here**:
7-13, 16 and 17. Three of the nine are closed.

The allocation was checked by content, not accepted by arithmetic: the six d3
paths were searched for across the whole corpus (absent everywhere, at every
version), and that branch's own diff was read to confirm it adds
`magic_illegal_overlap.json` and not `drc_signoff.json` — which is what made
16/17 unambiguously ours to fix rather than a duplicate of its work.

## 16 + 17 — the stale pin, re-derived and not widened

`d976999c4` [v1.11.45] added `reports/phase3/drc_signoff.json` to step 31's
`required_outputs` — correctly, three programs read that file — and did not
measure it into `matrix_d3_output_manifest.json`. The parity gate has been
reading **164 declared paths against 163 entries** ever since.

The fix is the one the gate itself names: measure the path. It resolves
non-empty at `benchmark-data/ic/spm/v1.9.96_gf180mcuD`, the admissible run root
five of its own siblings in the same step already cite — 1919 B, `"program":
"eda_report_audit:drc"`, the output of step 31's own gate clause. Recorded
`PRODUCED_BY_RUN`, decided LIVE by the same branch as the other 121.
**No assertion changed**; the two sides now genuinely pair one-to-one.
Regression sweep over every consumer of this manifest: every number identical
to the pre-change baseline except the one being fixed.

### The routing was NOT the root cause — checked, and the hypothesis is dead

The obvious explanation for 16/17 surviving days is that the gate which catches
them was never routed to the change that broke them. That was tested at the
commit itself rather than assumed: a worktree at `d976999c4`, then
`ci_targeted_test_select.py --base d976999c4~1`.

```
selected: 331 tests
  SELECTED  test_flow_manifest_declaration_parity
  SELECTED  test_matrix_d3_outputs_produced
  SELECTED  test_matrix_63x8_coverage
  SELECTED  test_matrix_mutation_ledger
```

All four were selected. The selector is correct and needs no change — **do not
"fix" it on the strength of this drift.** The gate was routed, costs under a
second, and would have failed. What did not happen is the 331-test selection
being RUN, which is the standing constraint on this host, not a routing gap.
Recorded as a refuted hypothesis so the next reader spends their time
elsewhere.

## 12 — a real finding that had been filed as weather

The renewal test drove 12 child items that each slept `0.45` s against a stall
window of `0.45` s. The renewal interval EQUALLED the interval the watchdog was
allowed to wait, so its green was scheduler jitter. On an idle box (load 3.45,
the file 2.1x faster than under load) it was STILL red, while its two
neighbours went green — and the child's tail shows seven of the twelve items
already reported before the kill. It was dying between renewals, not failing to
start.

Fixed by giving the renewal a margin (each item a third of the window, 24 of
them, so the run outlives the bound by 8x) with the ratio ASSERTED rather than
commented. Because making a timing test survivable is exactly the shape of a
relaxation, the opposite claim is now its own test: an item that cannot finish
inside the window MUST still be killed. Three mutations were run and each
reddened the arm it was aimed at. Whole file, idle host: `3 failed, 26 passed`
-> `2 failed, 28 passed`, twice.

## 10, 11, 13 — the host, proved rather than asserted

All three pass without any change to the repository once the box is not being
saturated by this file's own nested pytest children: 10 and 11 in the full-file
run at load 3.45, 13 alone at load 18-30 (`1 passed in 163.79s`). The failure
signature to recognise is `PROGRESS_PROTOCOL_INCOMPLETE: no pytest progress
stream was produced` — the child was killed before it emitted anything, i.e.
interpreter startup was scored as a hang. **That is a real weakness**: the
watchdog's stall clock starts before the child can possibly report, so
"has not started yet" and "stopped reporting" are the same state to it — the
same conflation this repository has already removed from `_vacuous_exit`,
`UNCHECKABLE` and rc=127.

**CORRECTION — it is not a weakness, it is a pinned trade-off.** An earlier
revision of this file called the startup blind spot a defect that was merely out
of validation reach. That was wrong in a way that matters, because it invites
the next reader to "fix" it and quietly make the repo worse.

The blind spot is real and its location is exact — `_watchdog.supervise()` sets
`last_progress = start`, so time spent launching counts as time without
progress. But a slow-starting child and a child that will NEVER start are
indistinguishable from the parent: neither has emitted a lifecycle event, and
output is explicitly not progress. The only thing separating them is how long
you are willing to wait.

The repository has already chosen, and one of these very reds is the test that
pins the choice. `test_live_collection_chatty_import_without_events_fails_closed`
drives a child that prints for 3 s while emitting no events, and asserts:

```
assert elapsed < 3          # the kill must BEAT the impostor
assert "WATCHDOG_STALLED:" in message
assert "COLLECT_CHATTER"  in message
```

Adding a startup grace large enough to survive a loaded host pushes the kill
past that bound and reddens this test. **Fail-closed-fast and survive-a-slow-
start are the same dial turned opposite ways.** Reds 10 and 13 under load are
the price of the setting the repo picked, not evidence it picked wrong — and
red 11 is the guard that would catch anyone trading it away silently.

For completeness, the mechanical scope, since it was measured: `stall_grace_s`
is one uniform window in `_owned_process_supervisor.run_owned` reaching
`_watchdog.supervise`, and six programs feed it — `_docker_watchdog` (EDA
containers), `gatekeeper_review` (the landing gate), `repo_hygiene_parallel`
(the ~57 min tier), `phase3_one_shot_runner` (real PnR/DRC/LVS),
`pytest_per_file_junit` (every test tier) and `_watchdog`'s own 1800 s lease. An
opt-in parameter defaulting to today's behaviour WOULD contain the blast radius
to one caller — so validation cost is not the reason to leave this alone. The
reason is the paragraph above.

## 7-9 — NOT_MEASURED, with the reason field filled in

Steps `0.5ic` and `1.6x` are ENFORCED in dimension 3 and no entry in
`matrix_mutation_ledger.MUTATIONS` covers them. `applies_to` is FROZEN by
design — a new step must redden this gate — so the red is the mechanism
working. What it asks for cannot be produced on any host, measured both ways:

* with a pre-withdrawal corpus clone, `--replay D3-UNDECLARED-ARTEFACT --step
  1.6x` -> `ALREADY_RED (4.5s)` and `--step 0.5ic` -> `ALREADY_RED (5.0s)`,
  both `baseline_rc=1`, both UNMEASURABLE;
* without one — the published state, `benchmark-data` `bcf2f94` withdrew all
  four cells on 2026-08-20 — the predicate SKIPS and both arms return
  `NOT_REPLAYABLE / UNREADABLE`.

There is no green->red transition to record, so `applies_to` may not be
widened: LOCK 3 exists to stop a number nobody measured. The manifest already
says it for `1.6x` — *"no PUBLISHED run predates it ... the truthful status is
UNPROVEN"* — while `matrix_cell_state()` still returns ENFORCED from NA/WAIVED
elimination alone. **Exclusion count for any enforcement figure: 2 cells,
carrying 3 of the 17 reds.** They close when the fourth state lands, and not
by anything done here.

## 1-6 — the evidence really is absent, and that was checked

The six cite run root `campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721`,
kind `home`. The remedy the test offers first is to re-point the record at a
root that carries the artefact — the same fix applied to 16/17 above — so it
was tried: `floorplan.def`, `placed.def`, `post_cts.def` and `post_hold.def`
exist **nowhere** in the corpus, in any cell, at any version. The classification
"needs evidence this repository does not hold" is confirmed by search, not
inherited.

## The three fixes were re-verified with the corpus BOUND as well

A fix measured only in the configuration that hides most of the population is
half a measurement, so all three were re-run against the pre-withdrawal clone —
the configuration in which 22 further reds are visible:

```
test_flow_manifest_declaration_parity          12 passed        (reds 16, 17)
..._nested_outcome_run_outlives_old_fixed...   passed           (red 12)
..._nested_outcome_run_is_killed_when_no_...   passed           (its control)
test_matrix_63x8_ledger                        52 passed
test_matrix_63x8_figure_coverage               12 passed
test_matrix_d7_outputs_list_complete           99 passed, 5 xfailed
```

None of the three is corpus-dependent, and the manifest entry added for step 31
resolves correctly when the corpus IS present — which is the only configuration
that can exercise its `PRODUCED_BY_RUN` branch at all. The four coverage
failures under BOUND are `test_every_na_cell_...`,
`test_no_cell_is_counted_enforced_...` (both owned elsewhere) and two revealed
by the corpus, not by this branch.

## The structural question, answered properly — and the answer is inverted

The brief's premise was "seven are stuck behind ONE d8 red; if that d8 is a
stale pin, seven close at once". The d8 half is false (dimension 8 is 347/347).
The *shape* of the question is the right one to ask, though, so it was asked of
the thing that actually sits behind most of this family: the corpus.

MEASURED, this branch, host load 1.74, the same files run with the pointer UNSET
and then BOUND to a pre-withdrawal `benchmark-data` clone (`146d665`, the commit
before `bcf2f94` withdrew all four cells) — i.e. exactly the counterfactual
"what would publishing a run tree buy":

```
corpus UNBOUND   11 red
corpus BOUND     33 red

closed by binding the corpus    0
revealed by binding the corpus  22
```

**Nothing closes. Publishing evidence does not retire a single one of these
reds — it uncovers twenty-two more.** The 22 are 11 further d3 step cells
(`0.5ic`, `1.6x`, 10, 16, 18, 21, 23, 29, 31, 34, 38, A9), 8 d3 guard tests
including `test_d3_run_root_discovery_is_live` and
`test_d3_unevidenced_cells_are_named_cell_by_cell`, and 2 coverage tests
including `test_the_enforcement_census_is_reported_for_humans`. How many of the
22 are real defects versus the known corpus-pointer precedence issue is NOT
claimed here; the direction and the count are what was measured.

Two things follow, and they matter more than the number:

1. **The corpus-absent skip is a blindfold, not a blocker.** Every figure this
   family publishes with the pointer unset is computed over a population where
   61 of 69 d3 cells declined to look. The census already says so — that is what
   its 49 NOT MEASURED cells are for — and this is the size of what they cover.
2. **Reds 7-9 are identical bound and unbound** (`3 failed, 123 passed` bound;
   `3 failed, 121 passed` unbound). The mutation-ledger reds do not move when
   the evidence arrives, which PROVES rather than argues the NOT_MEASURED
   classification above: they are waiting on the fourth-state ruling, not on a
   corpus. Anyone tempted to close them by publishing a run tree can stop.

Reds 1-6 also stay red with the corpus bound, which is the behaviour their own
module documents: an inadmissible `kind` is "decided without opening a file,
which is what makes the answer identical on a host that has a corpus and on one
that does not".

## Verification closed against the SELECTOR's answer, not against my own guess

Deciding for yourself which files a change could have broken is how a change
breaks one you did not think of. So the repo was asked instead —
`ci_targeted_test_select.py --base origin/main` on this branch names **46 test
files**, and all 46 have now been run, one pytest process each, corpus pointer
unset, on a quiet host:

```
46 of 46 run
43 files green
 3 files carry exactly the 11 reds documented above, all classified:
     test_matrix_d3_outputs_produced   6   (reds 1-6, owned elsewhere)
     test_matrix_mutation_ledger       3   (reds 7-9, NOT_MEASURED)
     test_matrix_63x8_coverage         2   (reds 14-15, owned elsewhere)
```

**No red on this branch is unaccounted for, and none of the three fixes broke
anything the selector can see.** The 22 files not previously run were all green,
among them several this work would not have thought to check —
`test_flow_compliance_check` (22), `test_signoff_required_outputs_completeness`
(21), `test_plugin_full_audit` (11), `test_programs_index_freshness` (11),
`test_ci_harness_timeout_ceiling_check` (86), `test_tools_and_integration` (19).

The one that mattered most was invisible from the outside:
**`test_d3_manifest_declaration_parity`** — 13 passed — is a SECOND parity gate
over the same manifest, distinct from `test_flow_manifest_declaration_parity`,
and the step-31 entry has to satisfy both. It was not on any list this work had
built by hand; the selector produced it.

## Landing note — this branch is conflict-neutral, and there is ONE trap

The brief said to split with `jfindings-63x8` and not duplicate it. That was
checked rather than assumed, by trial merge:

```
main + j63b                        clean, rc=0
main + jfindings-63x8              6 conflicts
main + j63b + jfindings-63x8       the SAME 6 conflicts
```

Identical sets, so **this branch adds zero conflicts** — all six are
`jfindings-63x8` against a main it predates. `test_matrix_63x8_coverage.py`, the
one file both branches edit, auto-merges: the two changes are in disjoint
regions and both survive.

**THE TRAP, and it is silent.** `matrix_d3_output_manifest.json` conflicts
(theirs-vs-main, present without this branch too), and the HEAD side of that one
conflict region contains three things while the theirs side contains one:

```
resolve --ours   : drc_signoff.json + lvs_verdict.json present = 2 of 2
resolve --theirs : drc_signoff.json + lvs_verdict.json present = 0 of 2
```

Taking `--theirs` — the natural move, since the incoming branch carries the
better `magic_illegal_overlap.json` provenance note — **silently deletes
`lvs_verdict.json` and `drc_signoff.json`**, reopening reds 16 and 17 and
leaving 164 declared paths against 162 entries. Taking `--ours` keeps both
entries and loses the improved note.

Neither side is right. Resolve by hand: **take theirs for the
`magic_illegal_overlap.json` `provenance_note` only, and keep HEAD for
everything else in that region.** Then run
`pytest -q programs/tests/test_flow_manifest_declaration_parity.py` — under a
second, and it is the check that catches this exact mistake.

## Reproduce

```
git worktree add -f <wt> origin/main --detach
cd <wt>/vibe-ic-marketplace/plugins/vibe-ic
export PYTHONDONTWRITEBYTECODE=1; unset VIBE_IC_BENCHMARK_DATA
for f in programs/tests/test_matrix_*.py; do
  python3 -m pytest -q -p no:randomly -p no:cacheprovider "$f"; done
python3 -m pytest -q programs/tests/test_flow_manifest_declaration_parity.py
python3 programs/matrix_mutation_ledger.py --replay D3-UNDECLARED-ARTEFACT --step 1.6x
```

Nothing here was obtained by widening an assertion, rewriting a baseline,
deleting a test or relaxing a rule deck. Two reds were closed by re-deriving a
measurement on the current tree, one by removing a race from a test that had
none of its own margin, and the rest are classified with their missing input
named.
