# j63b — the remaining 63x8 reds, re-enumerated on clean origin/main

Measured tree: `origin/main` @ `a00f53f20` [v1.11.66], fresh `git worktree`,
`PYTHONDONTWRITEBYTECODE=1`, corpus pointer UNSET, one pytest process per file
(19 files matching `programs/tests/test_matrix_*.py`), host load 25-45.

## HEADLINE, stated first because the brief asked for it loudly

**There is no d8 red. Dimension 8 is 347 passed / 0 failed, rc=0.**
The premise that "seven are stuck behind ONE d8 red" does not reproduce on
`a00f53f20`. `test_matrix_d8_missing_caught.py` is entirely green, in 83.11 s.
Nothing is waiting on it. The seven, whatever they were when counted, closed or
moved; they are not blocked by dimension 8 now.

## The live red set: 15, not 17

| # | id | class | note |
|---|----|-------|------|
| 1-6 | `test_matrix_d3_outputs_produced::test_d3_required_outputs_are_produced[step15,17,19,20,30,32]` | REAL FINDING (evidence) | 6 declared outputs cite run root `campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721`, kind `home` — a root this dimension searches on no host |
| 7 | `test_matrix_mutation_ledger::test_every_enforced_cell_carries_a_named_mutation[step0.5ic]` | NOT_MEASURED | see below |
| 8 | `...[step1.6x]` | NOT_MEASURED | see below |
| 9 | `test_matrix_mutation_ledger::test_the_coverage_is_complete_and_the_count_is_stated` | NOT_MEASURED | same two cells, aggregated |
| 10 | `test_matrix_63x8_coverage::test_live_collection_relays_finite_semantic_progress_past_old_bound` | HOST / self-contention | PASSES in isolation at load 44 |
| 11 | `test_matrix_63x8_coverage::test_live_collection_chatty_import_without_events_fails_closed` | HOST / self-contention | PASSES in isolation at load 44 |
| 12 | `test_matrix_63x8_coverage::test_nested_outcome_run_outlives_old_fixed_bound_with_semantic_progress` | HOST / self-contention | PASSES in isolation at load 44 |
| 13 | `test_matrix_63x8_census_freshness::test_the_census_block_is_fresh` | HOST / self-contention | WATCHDOG_STALLED > 60 s, 3-way concurrent |
| 14 | `test_matrix_63x8_coverage::test_every_na_cell_asserts_a_live_precondition` | REAL FINDING | d3:2309 and d7:375 `pytest.skip()` inside a cell test |
| 15 | `test_matrix_63x8_coverage::test_no_cell_is_counted_enforced_while_its_predicate_is_red` | THE RULING | 55 of 621 cells contradict their state: 6 measured red, 49 not measured |

Green in the same sweep: d1 (82), d2 (85+2xf), d4 (77), d5 (81+1xf), d6 (81+1xf),
d7 (97+3s+4xf), **d8 (347)**, d9 (80), ledger (52), figure_coverage (12),
waiver_single_source (4), write_record_scope (7), a3, a8, artefact_mutation_channel.

## Reds 10-13 are the host, and it is proved, not asserted

Re-run of exactly those cases, alone, on the same tree at load **44.61**:
`4 passed, 25 deselected in 10.93s`. They fail only inside the full
`test_matrix_63x8_coverage.py` run, whose own nested outcome-runs saturate the
box while the stall windows under test are 0.25 s and 0.45 s. This is a
statement about the harness's self-contention, not about the repository.
`origin/main` does not contain a defect these four are detecting.

## Reds 7-9: NOT_MEASURED, and here is the reason field

Steps `0.5ic` and `1.6x` are ENFORCED in dimension 3 and no entry in
`matrix_mutation_ledger.MUTATIONS` covers them. `applies_to` is a FROZEN list by
design — the ledger's own docstring says a new step must redden this gate the
minute the yaml changes — so the red is the mechanism working. What it asks for
cannot be supplied on any host today:

* **With a pre-withdrawal corpus clone** (`benchmark-data` @ `146d665`):
  `--replay D3-UNDECLARED-ARTEFACT --step 1.6x` -> `ALREADY_RED (4.5s)`,
  `--step 0.5ic` -> `ALREADY_RED (5.0s)`, both `baseline_rc=1`, both
  `UNMEASURABLE: red before the edit, so this pair proves nothing either way`.
* **Without one** (the published state): the d3 predicate SKIPS, and the replay
  reports both arms `UNREADABLE — pytest SKIPPED the cell (process rc=0), so
  this arm was NOT MEASURED`.
* **Why it can never be green here:** `benchmark-data` HEAD is `bcf2f94`
  ("withdraw all four published cells", 2026-08-20). No published run predates
  either step. The d3 manifest already says so in its own words for `1.6x`:
  *"no PUBLISHED run predates it, so its declared output has no run evidence yet
  and the truthful status is UNPROVEN"*, and every entry of both steps is
  recorded `status: UNPROVEN`.

So a mutation cannot demonstrate a green->red transition on these two cells in
either host state. Recording one anyway would be a fabricated measurement; and
`applies_to` may not be widened without one, which is the whole point of LOCK 3.

**Exclusion count for any enforcement figure: 2 cells (`0.5ic/d3`, `1.6x/d3`),
carrying 3 of the 15 reds.**

The one state that closes them honestly is the fourth state the owner ruled on:
`matrix_cell_state()` in dimension 3 returns ENFORCED from NA/WAIVED elimination
alone, with no knowledge of whether its predicate can run. That contract change
is `jfindings-63x8`'s, and reds 7-9 are its downstream consumers — they close
when it lands, and not before.

## Confirmations, run separately so neither claim rests on one sample

* **d8 is green, twice.** In the sweep: `347 passed in 83.11s`, rc=0. Re-run
  alone at load 29.75: `347 passed in 34.73s`. The second run reported rc=1 —
  and that was CORRECT and was not d8: `suite_write_guard` caught THIS report
  file appearing in the worktree mid-run, which is what it is for. No d8 case
  failed in either run.
* **Red 13 is the host.** `test_the_census_block_is_fresh` alone, same tree,
  load 18.48-29.75: `1 passed in 163.79s`. Inside the full-file run it dies on
  `WATCHDOG_STALLED ... > 60s` with `terminal event missing (stage=running)`
  while three nested pytest children compete for the box.

## What was NOT done, and why that is the answer rather than a shortfall

None of the seven reds this agent owns is a defect in `origin/main`, so none was
"fixed". Four are the harness starving itself and three are NOT_MEASURED with
the missing input named. The available ways to turn any of them green tonight
were: widen `applies_to` on a measurement nobody took, widen a watchdog window
until a saturated host squeezes under it, or re-point a citation at a corpus
that has been withdrawn. Each buys a green that is worth less than the red it
replaces, so none was taken.

The watchdog does have a real weakness underneath reds 10-13 — its stall clock
starts before the child can emit its first lifecycle event, so interpreter
startup under load is scored as a hang ("no pytest progress stream was
produced"). Fixing that means changing `pytest_per_file_junit.py`, the driver
every tier runs through, and showing it harms nothing means the full
`programs/tests` suite, which this host cannot carry. It is written down here
instead of half-landed.

## Reproduce

```
git worktree add -f <wt> origin/main --detach
cd <wt>/vibe-ic-marketplace/plugins/vibe-ic
export PYTHONDONTWRITEBYTECODE=1; unset VIBE_IC_BENCHMARK_DATA
for f in programs/tests/test_matrix_*.py; do
  python3 -m pytest -q -p no:randomly -p no:cacheprovider "$f"; done   # one process per file
python3 programs/matrix_mutation_ledger.py --replay D3-UNDECLARED-ARTEFACT --step 1.6x
```
