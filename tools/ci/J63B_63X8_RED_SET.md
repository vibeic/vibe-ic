# j63b — the remaining 63x8 reds, re-enumerated, classified and three of them closed

Measured tree: `origin/main` @ `a00f53f20` [v1.11.66], fresh `git worktree`,
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
watchdog's stall clock starts before the child can possibly report. The fix
belongs in `pytest_per_file_junit.py`, the driver every tier runs through, and
showing it harms nothing needs the full `programs/tests` suite this host cannot
carry. It is written down here rather than half-landed.

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
