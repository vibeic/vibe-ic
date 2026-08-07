# RESULT — spm × gf180mcuD (Benchmark IC campaign, plugin v1.9.96, 2026-08-07)

_Run date: 2026-08-07. IC: `spm` — serial-parallel integer multiplier
(N=32), PDK: gf180mcuD (`gf180mcu_fd_sc_mcu7t5v0`). Plugin: v1.9.96.
This supersedes the earlier `v1.5.66_gf180mcuD` record (plugin v1.5.66
era) — retired in the same commit as this one lands, per the publish
contract (a new version replaces the old, it does not sit beside it)._

## VERDICT

**PASS_WITH_WAIVERS.** Independently re-derived from raw artifacts, not
copied from the run's own summary:

- **GDS**: `chip_top.gds`, 1,230,264 bytes, present at
  `phase3/stage4/gds/chip_top.gds`,
  sha256 `fb08d9ed51f501ff4c3fbd6b9a30916c5927c86d586f07f147c9388388d8a255`.
- **Sign-off DRC** (KLayout, `gf180mcu.drc` — the PDK's own sign-off
  deck at `/foss/pdks/gf180mcuD/libs.tech/klayout/tech/drc/gf180mcu.drc`):
  `real_violation_total` in the regenerated report database: **0**
  (`reports/phase3/drc_signoff.json`, `tool_authentic: true`).
- **LVS** (netgen, power-aware): run's own report
  (`reports/phase3/lvs_power_aware.rpt`) — *"Circuits match uniquely"*
  under a power-aware gate netlist (PDK rails VDD, VSS, VNW, VPW as top
  ports, per-cell PG connectivity verified on 2,269 instances;
  `reports/phase3/lvs_verdict.json` status=PASS).
- **STA** (multi-corner OCV sign-off, real post-route SPEF,
  `reports/phase3/sta_mcorner_ocv.rpt`): worst setup slack **+0.57 ns**
  (FF process, min-RC, hold corner) MET; worst delay-max slack **+14.56 ns**
  (SS process, max-RC, setup corner) MET. Flat OCV derate applied
  (early=0.95, late=1.05).
- **DFT**: stuck-at ATPG coverage **100.00%** (866/866 faults covered,
  target 95%, `phase2/stage2/dft/atpg_coverage.rpt`,
  `reports/phase2/dft/atpg_coverage_gate.json` verdict=PASS).
- Confirmed via `flow_compliance_check.py --strict` against the run
  directory: **PASS=34 FAIL=0 MISSING=0**, exit 0,
  `Overall: PASS_WITH_WAIVERS`.

## What changed since v1.5.66 (root cause of this convergence)

**A real, chip-agnostic plugin defect — a stale ciel content-addressed
version hash — blocked DFT/ATPG on gf180mcuD and was fixed at v1.9.96
(commit `3d7c5a095`).**

ciel stages gf180mcu PDK data under a content-addressed
`ciel/gf180mcu/versions/<hash>/...` directory that moves every time the
`vibeic-eda` container's gf180mcu pin advances — unlike sky130A /
ihp-sg13g2, whose container paths are stable.
`pdk_cell_models.PDK_CELL_MODELS["gf180"]`,
`fault_atpg_run.PDK_CONFIG["gf180"]["cell_model"]` and
`fault_scan_chain_insert.SCAN_LIBERTY["gf180"]` each independently baked
in the same stale hash literal, so Step 11 (`fault cut`/`fault atpg`,
transition ATPG, `fault chain` scan insertion) failed with `cp: cannot
stat '<stale-hash-path>': No such file or directory` — disclosed
downstream as an apparent OSS-tool capability gap ("Fault is not
turnkey on the gf180 generic/UDP DFF forms"), which was actually a wrong
path, not a real tool limitation.

The fix (`pdk_cell_models.resolve_gf180_ciel_hash` +
`materialize_gf180_paths`) discovers the hash actually present in the
container via a caller-supplied docker runner and substitutes it into
the fallback path string; on any discovery failure the old literal
fallback is used unchanged (no regression risk). This cell's own run
went from the prior `v1.5.66` era's DFT capability-gap disclosure to the
real, measured **100.00% stuck-at ATPG** coverage cited above.

A second, earlier fix in the same session (metal-fill engine
reachability, v1.9.94 — already documented in the sibling
`v1.9.94_sky130A` RESULT.md) is also load-bearing for this cell's clean
DRC: this run resolves with **0** real DRC violations rather than the
density-coverage FAILs the v1.5.66-era run under a different fill-engine
state would have hit.

## Honest scope

**Known, pre-existing, plugin-wide gap — NOT specific to this cell:** the
P0 structural-RTL umbrella invokes 210 of 246 registered checkers; 36
never run at all (`argparse rejected the umbrella's argv`, e.g. gates
requiring `--rtl-dir`/`--masks`/`--vectors-json` the umbrella does not
currently supply). This is `INCOMPLETE`, not `FAIL`, and does not block
`flow_compliance_check --strict`'s exit code — but it means those 36
checkers' properties are UNCHECKED on this run, same as on every other
current run of the plugin. Not fixed in this session; out of scope for
this record.

**Deferred steps (WAIVED):** `rtl_gen` (deterministic program-first
generator, not AI — class registered `rtl_gen=null` so the step itself
is waived even though real RTL was produced), FPGA early-prototype and
final on-board sign-off (steps 6 and 39 — no DE10-class board-pin
contract for this IC class / no Quartus on host,
`ENV_UNAVAILABLE` machinery-sanctioned waiver, `review_required=true` in
`waivers.json`), simulation coverage-closure slot (step 4) and RTL≡netlist
equivalence-check slot (step 13) — both `PASS_WITH_WAIVERS` (#651, a slot
credited via waiver, not a bare pass; production tapeout review must
close them).

**Provenance note:** the RTL is deterministically generated
(program-first, no LLM) from this cell's own L-docs — sha256-reproducible
from the same input on any host. The design input documents are
campaign-shared with the sky130A and ihp-sg13g2 cells of this same
campaign round.

One cell (IC × PDK) of the open-PDK matrix. Nothing here is claimed for
any cell other than `spm × gf180mcuD` on plugin v1.9.96.
