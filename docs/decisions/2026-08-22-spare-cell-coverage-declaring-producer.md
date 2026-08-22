# The declaring producer of `reports/spare_cell_coverage.json`

**Date:** 2026-08-22
**Base:** `origin/main` a4caccefe (v1.11.69)
**Status:** decided

## Decision

**`spare_cell_coverage_check` is the declaring producer of
`reports/spare_cell_coverage.json`. `phase3_one_shot_runner` stops writing it.**

Step 18's flow declaration was right and is unchanged. This is shape 1 of the
three, and the reason it is shape 1 rather than shape 3 is set out under
"Why not two paths" below — that question was checked first, on real run data,
because two producers writing one path with different content is the shape that
makes a reader bind to neither.

The runner keeps `phase3/stage3/pnr/spare_cells.json`, its other declared
output. That file is the MEASUREMENT of the spare pool the step inserted. The
GRADE of that measurement belongs to the gate. **The step that inserts the
spares does not grade its own insertion.**

## What the two writers actually put in the file

Both wrote a payload with `verdict` and `status`. They graded the same run
against different floors and applied different rules, so the payloads are not
two views of one fact — they are two verdicts that can contradict each other.

| | `phase3_one_shot_runner` | `spare_cell_coverage_check` |
|---|---|---|
| when | inside the PnR step | at the step-18 gate, ~48 s later |
| density floor | the run's own `--spare-density` (0.0 – 0.2, caller's choice) | the gate's readiness minimum, 0.02 |
| `distribution_ok` | `len(distinct_sites) > 1` | `distinct >= max(2, ceil(count/2))` |
| `program` | `spare_cell_coverage (runner-emit)` | `spare_cell_coverage_check` |

Measured on the published `subservient` plan and on synthetic plans built by
the runner's own `_spare_count_from_density`:

```
--spare-density 0.02   ->  200 spares inserted
   runner-emit  status=PASS (target 0.02,  actual 0.02)
   checker      status=PASS (target 0.02,  actual 0.02)
   SAME PATH, SAME VERDICT

--spare-density 0.005  ->   50 spares inserted
   runner-emit  status=PASS (target 0.005, actual 0.005)
   checker      status=FAIL (target 0.02,  actual 0.005)
   SAME PATH, OPPOSITE VERDICT

--spare-density 0.0    ->    0 spares inserted
   runner-emit  status=PASS (target 0.0,   actual 0.0)
   checker      status=FAIL (target 0.02,  actual 0.0)
   SAME PATH, OPPOSITE VERDICT

200 spares stacked on 2 distinct sites
   runner-emit  distribution_ok=True   status=PASS
   checker      distribution_ok=False  status=FAIL
   SAME PATH, OPPOSITE VERDICT
```

`benchmark_verify_report` grades its sixth pillar — Design-for-ECO readiness —
by reading `status` from this literal path
(`benchmark_verify_report.py:572-574`). So the sign-off verdict on the ECO
budget was decided by which writer ran last. A run invoked with
`--spare-density 0` — no spare cells at all, no metal-only ECO possible after
tape-out — published `status: PASS` from the runner.

## Why not two paths (shape 3 was checked first, and refuted)

Shape 3 would be right if each writer carried something the other did not. It
does not hold, on two independent counts.

**1. The runner's payload carries no measurement that is not already in
`spare_cells.json`.** Every field is written to both, in the same block of
`phase3_one_shot_runner.py`:

| coverage field | also in `spare_cells.json` as |
|---|---|
| `count` | `count` (from the plan) |
| `placed_cells_est` | `placed_cells_est` |
| `target_density` | `target_density` |
| `actual_density` | `actual_density` |
| `tie_off_ok` | `tied_off` |
| `tie_off` (raised / never-ran / partial evidence) | `tie_off` |
| `distribution_ok` | derived from `instances[].llx/lly` |
| `verdict` / `status` | — the self-grade, and nothing else |

The only content unique to the runner's file is a verdict computed against a
floor the same run chose. That is exactly what the gate exists to refuse: the
checker's own comment already says a plan's self-target "can never relax the
readiness floor below what the gate asks for". Giving that self-grade its own
declared path would publish it as a second opinion on the sign-off question.
There is one sign-off question here and one gate entitled to answer it.

**2. In 34 published run roots, the runner's payload survives zero times.**
`grep -rl 'spare_cell_coverage (runner-emit)' benchmark-data/` returns nothing;
every published `reports/spare_cell_coverage.json` carries
`"program": "spare_cell_coverage_check"`. The write ledger of
`ic/spm/v1.10.18_sky130A` dates it: `spare_cells.json` at mtime
`1786273818.075`, `reports/spare_cell_coverage.json` at `1786273866.398` — the
gate overwrote the runner 48 seconds later, on every run. Nothing downstream
has ever read the runner's version, so removing it strands no reader.

## The gap that removing the clobber alone would have left

The row this decision closes was recorded rather than repaired because "fixing
the clobber ALONE would turn the cell green while leaving the real gap
invisible." The real gap is this:

`spare_cell_coverage_check` **read the path it writes.** `evaluate_coverage`
took the JSON found at `reports/spare_cell_coverage.json` and preferred its
`actual_density` over the plan's. On a first run that file is the runner's; on
any re-run it is the gate's own previous verdict. Reproduced:

```
run 1  healthy plan (200 spares / 10000 cells)  -> exit 0, actual_density 0.02
       plan replaced by a starved one (10 spares / 10000 cells, 0.001)
run 2  same project, gate re-run                -> exit 0, and the file says
       {"actual_density": 0.02, "count": 10, "verdict": "PASS"}
```

Ten spares reported at 2 % density, in a file that contradicts itself
(0.02 x 10000 = 200, not 10), and the gate exits 0. This is reachable in the
real flow: `phase3_one_shot_runner` skips the entire PnR step — and with it
the spare insertion — when the DEF exists and the geometry/producer cache is
valid (`if def_existing.is_file() and _cache_ok:`). A resumed run therefore
does not refresh the file, and the gate grades the new state from the old
verdict.

That defect exists only because the reader bound to a path two writers owned.
Deleting the runner's write would have made the gate green and left the
self-read in place. Both are fixed here.

## The change

* `phase3_one_shot_runner.py` — the coverage-payload emit is removed.
  `spare_cells.json` is unchanged and still carries every measurement. The
  step's log line now reports `distinct_sites=<n>` (the measurement) instead of
  `dist_ok=<bool>` (a grade the gate computes differently).
* `spare_cell_coverage_check.py` — `evaluate_coverage` loses its
  `coverage_summary` argument; `_resolve_paths` becomes `_resolve_input` and
  returns one path. The verdict is recomputed from `spare_cells.json` on every
  invocation. The report's `coverage_summary_json` key — which named this
  program's own output as an input — is replaced by an exhaustive `inputs`
  list. Version 1.0.0 -> 1.1.0.
* `flow/phase1_phase2_phase3.yaml` — step 18's `required_outputs` gains a
  comment naming the sole producer and why. The declaration itself is
  unchanged: it was already correct.
* `skills/design-for-eco/SKILL.md` — the stage3 step no longer claims to emit
  the coverage report.

No spare or ECO cell is deleted, moved, or made optional by any of this. The
insertion path, the `keep`/`dont_touch` protection, and
`spare_cell_preservation_check` are untouched.

## The negative control

`programs/tests/test_spare_coverage_single_declaring_producer.py` goes RED if
the second writer comes back, in either of the two ways it can.

*A second writer appears* — restoring the runner's emit:

```
E   AssertionError: phase3_one_shot_runner names reports/spare_cell_coverage.json
    in non-comment code again; step 18 declares spare_cell_coverage_check as that
    path's producer and the runner's payload grades the run against its own
    --spare-density:
      cov_path = project / "reports" / "spare_cell_coverage.json"

E   AssertionError: reports/spare_cell_coverage.json has exactly one declaring
    producer (spare_cell_coverage_check.py); these also write it:
    ['phase3_one_shot_runner.py']
```

The scan runs over every program, not only the runner, so a third writer trips
it too.

*Something written at the path reaches the verdict* — restoring the self-read:

```
E   AssertionError: gate exited 0 on a plan with 10 spares in 10000 cells
    (0.001 < 0.02); a payload planted at its own output path rescued it.
    Verdict written: {'target_density': 0.02, 'actual_density': 0.02,
    'count': 10, ..., 'verdict': 'PASS', ...,
    'coverage_summary_json': 'reports/spare_cell_coverage.json',
    'status': 'PASS'}

E   AssertionError: re-run exited 0: the gate carried run 1's density over
    run 2's plan.

E   AssertionError: evaluate_coverage takes
    ['spare_plan', 'coverage_summary', 'target_density']; the only inputs are
    the plan and the gate's floor
```

## Consequences for the published corpus

Published `reports/spare_cell_coverage.json` artefacts are already the
checker's payload, so no published verdict changes. Their
`coverage_summary_json` field records that the gate read a file at its own
output path; on those runs the file was the runner's and its `actual_density`
was computed by the same formula from the same plan, so the recorded densities
stand. The staleness this decision removes needed a re-run over a changed plan,
which no published root has.

Seven of the eight published roots that carry a committed verdict also carry
the plan it was derived from; the checker was re-run over all seven at
a4caccefe and at this change, and no verdict, density, count or reason moved:

```
OK  committed=PASS  main=PASS  head=PASS  evaluation/phase1_parity/espi
OK  committed=PASS  main=PASS  head=PASS  evaluation/phase1_parity/lpc
OK  committed=PASS  main=PASS  head=PASS  evaluation/phase1_parity/mdio
OK  committed=PASS  main=PASS  head=PASS  evaluation/phase1_parity/sgmii
OK  committed=PASS  main=PASS  head=PASS  ic/caravel_user_project
OK  committed=PASS  main=PASS  head=PASS  ic/sha256
OK  committed=PASS  main=PASS  head=PASS  ic/subservient
```

The eighth, `ic/edge_llm_accel`, is UNDETERMINED here — not clean, not moved.
Its committed verdict is the only published FAIL (`tie_off_ok: false`, 27121
spares), and it cannot be recomputed because the plan it was derived from is
not in the tree: `ic/edge_llm_accel/steps/18_.../spare_cells.json` is a symlink
to `ic/edge_llm_accel/phase3/stage3/pnr/spare_cells.json`, which the run
records as 4 865 163 bytes and which does not exist. That is what could not be
read; nothing is concluded from it either way. The verdict itself is the
checker's own payload and this change does not touch how it was computed.
