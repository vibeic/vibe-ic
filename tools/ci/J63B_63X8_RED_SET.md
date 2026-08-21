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
| 10 | `63x8_coverage::..._relays_finite_semantic_progress_past_old_bound` | **REAL FINDING — FIXED** | thin margin (2.1x); killed BETWEEN collections, not at startup — see below |
| 11 | `63x8_coverage::..._chatty_import_without_events_fails_closed` | NOT_MEASURED (quiet host) | PASSES at load 3.45. It is also the test that PINS the fail-closed-fast choice — see 10, 11, 13 below |
| 12 | `63x8_coverage::..._nested_outcome_run_outlives_old_fixed_bound...` | **REAL FINDING — FIXED** | zero margin by construction; fixed + negative control added |
| 13 | `63x8_census_freshness::test_the_census_block_is_fresh` | NOT_MEASURED — cause NAMED | one d3 item is 18.95 s against a 60 s window; no intra-item heartbeat exists — see below |
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

## Red 12's fix measured against the standard that condemned it

The prior session's rate for this exact node was **4/10 red on unmodified
`origin/main`**, measured by running it alone ten times. The fix is measured the
same way so the two numbers are comparable, and then again under contention
harsher than the one that produced the red:

```
ARM 1  the pair alone, ten consecutive runs        10/10 green  (~6.1 s each)
ARM 2  THREE concurrent full-file runs, load 53.18
         conc1  2 failed, 28 passed   red 12 + control: green
         conc2  2 failed, 28 passed   red 12 + control: green
         conc3  2 failed, 28 passed   red 12 + control: green
```

Load 53.18 is above the 25-45 that produced the original red and far above the
3.45 idle run where it still failed. The two failures in each concurrent run are
the NA-skip contract and the fourth-state ruling — both owned elsewhere. 4/10
red to 0/10 and 0/3, against a harder condition.

**And an honest refinement to 10 and 11.** They did NOT reproduce in any of the
three concurrent runs at load 53, having failed in the original sweep at load
25-45. Load average alone does not predict them; the specific interleaving does.
They are rarer and more intermittent than a single observation suggests, which
strengthens rather than weakens the reading that they are not repository
defects — and it is stated here so nobody quotes a rate this work never
measured.

## 10 — the same disease as 12, one notch less acute, and I nearly missed it

This was filed as host contention for most of this work, on the strength of it
passing on a quiet box. Then its actual failure text was read, which should have
happened first:

```
WATCHDOG_STALLED: ... did not advance for > 0.3s
PROGRESS_PROTOCOL_INCOMPLETE: terminal event missing (stage=collecting)
```

**`stage=collecting` is the load-bearing word.** The child had STARTED and was
emitting events; it was killed BETWEEN two collections. That is red 12's
disease, not red 11's startup problem — and the construction says so: seven
files each sleeping `0.14` against a `0.30` window is a **2.1x** margin, and
2.1x is not much once per-file import and collection machinery land on top of
the sleep.

Same treatment as 12, and **the window is untouched at `0.30`**: 21 files at a
SIXTH of the window (`1.05 s` total, still over the `0.8 s` bound the test
exists to prove work may cross), with the ratio asserted rather than commented.

Two mutations, run, each reddening the arm it aims at:

```
window 0.30 -> 0.02  (renewals cannot keep up)  -> 1 failed, WATCHDOG_STALLED
ratio  /6   -> /2    (the old thin shape)       -> assert (0.15*6) <= 0.3 fails
                                                   before the run even starts
```

Stability: **10/10 green alone** (~2.1 s each), and green in three CONCURRENT
full-file runs at load 31.54.

**One honest observation from those concurrent runs, which is not a new red.**
`test_every_cell_has_a_live_outcome_and_the_outcome_run_is_not_starved` failed
in 2 of the 3. It appears in NO prior unbound run of this file. Three concurrent
full-file runs genuinely starve the nested outcome run, which is the exact
condition that test detects — the harness catching an abusive measurement
configuration this work created, not a defect and not caused by this change.

## 13 — not "the host". One item, 18.95 s, against a 60 s window

Red 10 taught this report to read the failure text before classifying, so red 13
got the same treatment. Its message is the same shape as 10's —
`terminal event missing (stage=running)` — the child had started and was
emitting, then stopped for over 60 s. So: which item?

```
slowest durations, test_matrix_d3_outputs_produced.py, load 5.60
  18.95s  test_d3_the_producer_oracle_answers_both_ways
   1.03s  test_d3_the_write_ledger_can_only_subtract_evidence
   1.00s  test_d3_the_write_ledger_binds_production_to_the_step
   0.92s  ... and everything else below a second
```

**One item is 18× its nearest neighbour**, and it is a THIRD of the 60 s
no-progress window on an almost idle box. Under the three-way contention that
produced the red, 3x is not a stretch.

And it is not a slow test anybody should speed up. `producer_evidence` is
already `@lru_cache(maxsize=None)`, and its docstring already says what the time
is: `writers_of` builds an AST index over the tree, deferred so that "only a run
that reaches an UNEVIDENCED verdict should pay for it". The cost is one-time,
cached, and deliberately lazy. There is nothing to optimise away.

**The finding is structural, and it is the same root as red 11's.** pytest emits
lifecycle transitions at item BOUNDARIES, never during an item, so the driver
has no way to tell "one long item making progress" from "hung". Any item whose
runtime is a material fraction of the stall window is indistinguishable from a
hang, and this one is a third of it before the box is even busy.

That makes the honest remedy an intra-item heartbeat in the progress protocol —
the same driver change scoped and declined under 11 above, for the same reason.
What is NOT the remedy is widening the 60 s window until an 19 s item fits under
a contended one; that is the relaxation this campaign exists to refuse. Red 13
stays open, but it is now a named mechanism with numbers rather than a shrug at
the machine.

## 11 — the host, proved rather than asserted

All three pass without any change to the repository once the box is not being
saturated by this file's own nested pytest children: 10 and 11 in the full-file
run at load 3.45, 13 alone at load 18-30 (`1 passed in 163.79s`). The failure
signature to recognise is `PROGRESS_PROTOCOL_INCOMPLETE: no pytest progress
stream was produced` — the child was killed before it emitted anything, i.e.
interpreter startup was scored as a hang. The watchdog's stall clock starts
before the child can possibly report (`_watchdog.supervise()` sets
`last_progress = start`), so "has not started yet" and "stopped reporting" are
one state to it. That looks like the conflation this repository has removed from
`_vacuous_exit`, `UNCHECKABLE` and rc=127 — and it is NOT one. See directly
below.

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

**CORRECTION — that state exists NOWHERE, and this file previously implied it
was in flight.** Measured, not assumed: `jfindings-63x8`'s branch does not touch
`matrix_cell_state` in ANY dimension, and on main `NOT MEASURED` appears only as
a reporting string inside `test_matrix_63x8_coverage.py:2167` — never as a state
a dimension can return. Reds 7-9 are not waiting on a branch; they are waiting
on work nobody has started. A reader who took the earlier wording would have
waited for a delivery that was never coming.

What it would cost, measured — **9 producers and 7 consumers**:

```
defines matrix_cell_state()   d1 d2 d3 d4 d5 d6 d7 d8 d9          (9)
reads it                      test_matrix_mutation_ledger
                              test_matrix_63x8_coverage
                              test_matrix_waiver_single_source
                              test_d7_single_tree_lookup_is_lazy
                              matrix_d7_artifact_graph
                              matrix_63x8/substitution.py
                              matrix_63x8/README.md               (7)
```

A fourth state is a cross-cutting contract, not a one-line return: every
producer must decide when its predicate CANNOT run, and every consumer must stop
folding that answer into one of the three it already handles. It is not authored
here because it was assigned, and two agents writing one contract in parallel is
the duplication this split exists to prevent — but **"assigned and unstarted" is
a different fact from "pending on a branch"**, and this is the one that is true.

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
22 are real defects versus the known corpus-pointer precedence issue was left
unclaimed in an earlier revision of this file. It is claimed now, below, and it
matters — because "22 reds revealed" reads as "22 hidden defects", and that is
not what they are.

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
 3 files carry 11 reds, all classified:
     test_matrix_d3_outputs_produced   6   (reds 1-6,   owned elsewhere)
     test_matrix_mutation_ledger       3   (reds 7-9,   NOT_MEASURED)
     test_matrix_63x8_coverage         2   (reds 14-15, owned elsewhere)
```

**The arithmetic, since 11 is not 17 minus 3 and a reader should not have to
work that out.** Seventeen on clean main; three fixed here (12, 16, 17) leaves
fourteen; this sweep observed eleven. The missing three are **10, 11 and 13** —
the load-intermittent ones. They did not fire in this sweep, and they did not
fire in three concurrent full-file runs at load 53 either. That is a property of
those three, documented in their own section above, not a discrepancy: nobody
has a rate for them and this report does not offer one.

**So no red on this branch is unaccounted for, and none of the three fixes broke
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

### What the 22 actually ARE — triaged, and most are not defects

Every one was read for its own reason rather than counted. Six classes:

| n | class | evidence |
|---|-------|----------|
| 12 | **UNEVIDENCED against the clone that was bound** | the recorded run root is not in it — `benchmark-data/ic/sha256/clean_run_v1427_20260715` (step 10), `benchmark-data/ic/subservient` (step 21). Not "the flow fails to produce"; the evidence lives in run roots this clone lacks |
| 4 | **PINS that moved** | `the cost of closing the unevidenced class moved: measured 453282 B over 23 entries, pinned 386857 B`, plus three population/set pins that re-derive once the population is visible |
| 2 | **host-dependent counts** | `141 of 164 declared entries verified live … and that number is host`-dependent by its own words; `run_root_discovery_is_live` |
| 2 | **coverage, downstream** | census/live-outcome reporting moving because d3's state moved |
| 1 | **a REAL finding** | `21 manifest record(s) cite a run root no checkout carries while THIS COMMIT answers the entry` — a genuine stale-manifest defect |
| 1 | **the known precedence defect** | the self-certification probe drives `benchmark-data/ic/u_hawaii_adc`, "which lives in this repository and must resolve" — the bound pointer overrides the in-repo root |

So the blindfold is not covering twenty-two defects. It is covering **four pins
that need re-deriving, one real stale-manifest finding, one precedence defect,
and twelve cells whose evidence sits in run roots nobody staged** — the last of
which depend entirely on WHICH roots a publisher would stage, not on whether the
flow produces the artefacts.

That sharpens the headline rather than softening it. Publishing a run tree still
closes zero of the seventeen. What it additionally does is force four pins to be
re-derived and surface one genuine defect — a smaller and much more specific
bill than "22 more reds", and one somebody can actually plan.

**Caveat, stated because it bounds everything above:** this was measured against
a clone at `146d665`, one commit before the withdrawal. No CI host can reproduce
it today. It is the counterfactual "what the corpus showed the day before it was
withdrawn", which is the right question for deciding whether to re-publish, and
is not a claim about any host's current state.

### The one real defect in the 22, made actionable

`test_d3_no_record_cites_an_absent_run_this_commit_can_answer` is the only
unambiguous defect the corpus reveals, so it is written out rather than left as
a table row. **21 manifest records name a run root the REPOSITORY does not
carry, while a different admissible root answers the same entry.** The
population, by cited root:

```
benchmark-data/ic/caravel_user_project   steps D1 (x2), 4, 9, …
benchmark-data/ic/sha256                 step 5
benchmark-data/ic/sha256/clean_run_v1427_20260715   step 10
benchmark-data/ic/u_hawaii_adc           steps A1, A2, A3, A4, A5, A6 (x2), …
```

The remedy is the same shape as the step-31 fix in this branch — re-point each
record at the root that actually answers it — and **it was NOT done here, for a
reason that is not squeamishness.** The root that answers is only visible with a
pre-withdrawal clone bound. Re-pointing 21 committed records at roots the
published corpus no longer carries would replace one unreproducible citation
with another, and would bake a corpus state that upstream deliberately removed
into a fixture every host reads. That is a worse artefact than the red.

It is repairable by exactly one kind of author: someone with the run trees
staged, re-deriving each record against what they publish, in the same change
that publishes it. Until then it sits with reds 1-6 — a real finding whose
missing input is named.

Note also that the module already degrades correctly around it: the
`PRODUCED_BY_RUN` branch searches every admissible root and reports
`STALE MANIFEST RECORD … which root answered instead`, so nothing silently
passes on a stale citation. The test exists to prompt the repair, not to guard
against a false green.

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

### The trap is ALL SIX regions, and one of them is a duplicate of main

The manifest is not special. Every one of the six conflicts is asymmetric in the
same direction — main's later content sits on the HEAD side and a one-sided
`--theirs` deletes it:

```
phase1_phase2_phase3.yaml        ours  89 lines   theirs  17
matrix_d3_output_manifest.json   ours  17         theirs   1
matrix_63x8/README.md            ours   2         theirs   2
matrix_63x8/flowref.py           ours  20         theirs  75
test_matrix_63x8_ledger.py       ours 114         theirs  27
test_matrix_d2_falsifiable.py    ours 241         theirs 380
```

**So the right instrument is a REBASE of `jfindings-63x8` onto current main, not
a merge.** A rebase replays its commits one at a time against what main now
says and forces each decision to be made on its own; a single six-region merge
invites exactly one `--theirs` keystroke that silently drops main's work in
three files.

And the yaml region is worth naming, because it is not a disagreement at all —
**both sides are the same fix, authored twice.** They declare
`reports/phase3/magic_illegal_overlap.json` on step 31 for the same dimension-7
reason (`gate_output_read_elsewhere`), in different prose. Main already carries
it:

```
required_outputs on main includes magic_illegal_overlap.json   True
d3 manifest entry on main                                       PRESENT (UNPROVEN)
landed by                                                       ff5071caa
```

So that branch's step-31 d7 commit is superseded — the declaration and the entry
are on main already, and what it still adds there is a richer `provenance_note`,
which is a text merge and not a finding. This is the same disease as the premise
this whole report opens by correcting: **a list written before main moved.**
Worth re-deriving that branch's remaining findings against current main before
spending review on them.

### How much of that branch is still live — measured, and most of it is

Saying "a branch predates main" is not a verdict on its content, so the content
was checked commit by commit. Of its nine commits, **seven add a test function
that does not exist on main** — genuinely new work, and the reason the split was
worth making. Two add no test, and both of those are superseded:

* **`matrix(d7)` step 31's extraction-feedback verdict** — main declares the
  path and carries the manifest row already (`ff5071caa`). What remains is a
  richer `provenance_note`: a text merge, not a finding.
* **`matrix(figures)` the 11 anchored figures** — this one is worse than
  superseded, it is a REGRESSION if taken. It re-derives the figures to
  `142` entries and `166` blocking clauses. Main has since re-derived further:

```
main today            164<!--figure:required_output_entries-->
                      177<!--figure:blocking_clauses-->
that commit sets      142                166
test_matrix_63x8_figure_coverage on main:  12 passed
```

Resolving that region toward theirs walks two published figures backwards and
reddens a gate that is currently green.

This is the strongest argument for the rebase: replayed one commit at a time
against current main, the figures commit fails its own gate immediately and the
d7 commit shows up as an empty or prose-only change. Merged as one six-region
blob, both land silently.

**Nothing here says that branch is stale work.** Seven ninths of it is new, and
two of the reds this report leaves open are its to close.

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
