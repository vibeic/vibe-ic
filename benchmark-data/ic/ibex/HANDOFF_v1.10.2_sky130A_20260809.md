# ibex x sky130A — plugin v1.10.2 — RUN PAUSED (not converged, not failed)

_Recorded 2026-08-09. This is a HANDOFF record for an INCOMPLETE run, deliberately
not published as a `v<version>_<PDK>` evidence cell: `benchmark_evidence_publish.py`
refuses a non-converged run, and it is right to._

## VERDICT: INCOMPLETE — WOUND DOWN ON PURPOSE

**This run did not fail. It also did not converge. It was stopped for resource
re-prioritisation (gate hardening took priority over cell convergence).**

Recording this distinction precisely matters: `benchmark-data/ic/INDEX.md` defines
`RETAINED FAILURE` as "an audit ran and did NOT converge". That is **not** this.
No audit reached a terminal verdict here. Filing this as a FAIL would assert a
measurement that was never taken — the same class of error as filing it as a PASS.

## THE ONE THING A RESUMER MUST NOT MISREAD

**The stuck-at ATPG gate never ran. Nothing in this run says anything about the
95% foundry floor.**

The transition-fault (TDF) gate PASSED, and it is easy to mistake that for "DFT is
fine". It is not the same gate. The cell that was caught shipping a false
convergence today (`caravel_user_project/v1.9.43_sky130A`) **also** scored
`tdf_test_coverage_pct: 100.0` and **also** passed its TDF gate — and then failed
stuck-at at **89.59%** against the 95% floor. TDF passing is exactly the signal
that would mislead you here.

The only stuck-at artifact in the tree is a pre-flow stub:

    reports/phase2/dft/coverage.unmeasured.json
    {"error": "unsupported pdk: unmapped ...", "pdk_sniff": "no configured
     library's cells found in the resolved netlist"}

There is no `coverage.json`, no `test_coverage.json`, no `atpg_coverage_gate.json`.
**Treat the 95% floor as an OPEN question for ibex.**

## What genuinely passed (measured, re-readable from artifacts)

### Phase 1 — complete
28 L-docs emitted, 100% coverage.

### Phase 2 — `PASS_WITH_WAIVERS`
- `yosys_synth` PASS: `netlist_yosys.v`, 31,204 cells, top `ibex_core`, frontend `yosys_slang`.
- `rtl_gen` WAIVED -> REUSED-IP path; 23 vendor RTL files staged (ibex is a REUSED-IP cell).
- `lec_equivalence` **INCONCLUSIVE** (177/2240 proven). This is NON-CONVERGENCE of the
  solver, **not** non-equivalence: no counterexample was produced. Known, disclosed
  yosys sequential-depth capability gap. Neither a false PASS nor a false FAIL.

### DFT scan insertion — succeeded (superseding a phase2 skip)
Phase 2 logged `dft_scan_insertion SKIP (rc=2)`. Phase 3 rebuilt it successfully.
From `reports/phase2/dft/scan_chain.json`:
- internal chain **1937** flops, boundary **262**, total 2199
- `chain_length_matches_flop_count: true`, `problems: []`, `ok: true`
- tech-mapped netlist `ibex_core_synth.v`, liberty `sky130_fd_sc_hd__tt_025C_1v80.lib`
- one warning worth carrying forward: `Detected flip-flops with clock different from clk_i`

### Transition-fault ATPG — real PASS
From `reports/phase2/dft/transition_coverage.json`:

| field | value |
|---|---|
| `tdf_test_coverage_pct` | **100.0** |
| `floor_pct` | 90.0 -> `ge_floor: true`, `verdict: PASS` |
| `tdf_fault_coverage_pct` | 60.0 |
| sampled / graded | 370 / 370 of 217,524 total TDF faults (disclosed sample) |
| detected / redundant / **aborted** | 222 / 148 / **0** |
| `budget_truncated_faults` | **0** |
| solver / wall | `kissat`, `wall_budget_sec: 7200` (not hit) |

Zero aborted and zero truncated: this is a real measurement, not a budget artifact.
Note the denominator honestly — test coverage excludes the 148 redundants (222/222),
which is standard; raw fault coverage over the sample is 60.0%. Both are reported.

### Phase 3 — barely started
**No `phase3/` directory, no `.def`, no `.gds` were ever produced.** PnR, CTS, route,
DRC, LVS, STA, and stuck-at ATPG all lie AHEAD of where this stopped. (An earlier
handoff in this campaign claimed phase3 had progressed "through PnR/DRC/LVS"; that
was checked against the run tree and is false.)

Consequently the known ibex Fmax floor (spec 100 MHz vs ~47-77 MHz achievable in the
OSS flow at sky130A) was **never exercised** — `sta_achievable_fmax_report.py` runs at
phase3 STA, which was never reached. No `achievable_fmax.json` exists. That floor
remains a prior expectation, not a result of this run.

## Exact resume point

| item | value |
|---|---|
| host | `192.168.1.121` |
| run dir | `/home/reyerchu/_ibex_v1102_sky130A_run` (left INTACT) |
| runner container | `ibex_v1102_sky130A` |
| image | `ghcr.io/vibeic/vibeic-eda:0.2.75` (matches plugin `DEFAULT_IMAGE` anchor) |
| plugin | **1.10.2 exactly**, md5-verified against repo HEAD at run start |
| top / PDK / clock | `ibex_core` / `sky130A` / `clk_i`, SDC period 10 ns |
| last completed step | transition-fault ATPG (finished 23:14) |
| step in flight at stop | `lec_run.py` (phase3 LEC), allowed to finish on its own |
| restart from | phase 3, at the step AFTER LEC — i.e. PnR onward. Phase 1, phase 2 and DFT/TDF outputs are valid and need not be re-derived. |

**Version caveat:** commit `8c2527182` (`sta_signoff_rigor_check` verified
`check_types` COVERAGE but never CONTENT) is tagged **v1.10.3** and is therefore
**NOT** present in this run. Neither is `e6257c6b3` (v1.10.3 published-tree
advisory). Do not resume assuming either fix is in effect.

**Wind-down was graceful, not a hard kill.** No solve was interrupted mid-flight:
a watcher (`/home/reyerchu/_ibex_graceful_stop.sh`, log
`/home/reyerchu/_ibex_graceful_stop.log`) waited for the in-flight LEC to exit on
its own, then SIGTERMed the supervisors so no further step could launch.

## SYSTEMIC FINDING — L20 is unextracted across essentially the whole cell set

This outlived the run and is the most transferable thing it produced.

Surveying every `L20_DFT_SCAN_TOPOLOGY.json` under `benchmark-data/ic/`:
**8 of 9 ICs carry a completely unextracted L20** —
`applicability: APPLICABLE`, `extraction_status: NOT_YET_EXTRACTED`,
`dft_present: false`, `scan_chains: []`. That includes **all four converged
reference cells** (`spm` x3, `u_hawaii_adc`). The single exception,
`edge_llm_matmul_accel`, carries 26 chains only via its AI/merged track; its
`program_track_raw` L20 is the same empty skeleton.

So the Phase-1 L20 extractor has **never** produced an extracted state for the
program track on any canonical IC.

Two gaps compose to make this load-bearing, both already named in the plugin's own
comments but apparently never measured together:

1. Phase 1 never marks L20 extraction claimed -> every design sits in `NOT-RUN` forever.
2. `dft_atpg_coverage_check.l20_dft_applicability`'s docstring flags as "KNOWN AND
   DELIBERATELY UNTOUCHED" that a layer which *does* claim extraction and records no
   DFT is folded into `asserts_dft=True` by the `is_extraction_claimed` term — "the
   one state that would legitimately earn the downgrade".

Net: **no design can reach the DFT floor downgrade by any automatic path.** The only
reachable route is a human hand-authoring `applicability: NOT_APPLICABLE`. Every
canonical cell is therefore held to a 95% foundry sign-off floor its design input
never asked for.

Why it stayed invisible until now — the version arithmetic matters:
- The tightening is commit `4b7ba5b66` ("an UN-EXTRACTED L20 is UNKNOWN, not a
  declaration that no DFT is required"), which landed at plugin **v1.9.80**.
- `caravel_user_project/v1.9.43_sky130A` predates it, so its published
  `atpg_coverage_gate.json` records `floor_enforced: false`, `verdict: INFORMATIONAL`
  at 89.59% — that downgrade is *how* a sub-floor run got shipped as converged.
- `spm` clears the floor on merit (100.0%, `floor_enforced: true`) — a genuine pass,
  not a masked one.

v1.9.80 correctly fixed a real non-monotonicity (before it, deleting L20 made the
gate STRICTER than leaving an empty skeleton). It also converted a dormant Phase-1
extraction gap into a live blocker. ibex, running v1.10.2, would have been the first
cell to meet it head-on — had it reached the stuck-at gate.

**This is a Phase-1 extraction gap, chip-agnostic, affecting the whole cell set.**
It is recorded here only; it was NOT fixed in this task, and per the NO-MIX rule any
fix must land as its own version-less PR, never in a commit carrying benchmark
results.

## Honesty ledger

- Nothing in this document is copied from the run's own summary; every number was
  re-read from the named artifact.
- No number is stated for any gate that did not run. The stuck-at floor, DRC, LVS,
  STA, GDS and Fmax are all recorded as NOT MEASURED rather than estimated.
- The run directory is intact on `.121` and is the authority; if it is reaped before
  resume, this record's phase-3 claims cannot be re-derived and the run must restart.
