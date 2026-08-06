# RESULT — spm × sky130A (Benchmark IC campaign, plugin v1.9.94, 2026-08-07)

_Run date: 2026-08-07. IC: `spm` — serial-parallel integer multiplier
(N=32), PDK: sky130A (`sky130_fd_sc_hd`). Plugin: v1.9.94. Container:
`vibeic-eda:0.2.70`. This supersedes the earlier `v1.5.65_sky130A` record
(2026-07-24, plugin v1.5.65 era) — retired in the same commit as this one
lands, per the publish contract (a new version replaces the old, it does not
sit beside it)._

## VERDICT

**PASS_WITH_WAIVERS.** Independently re-derived from raw artifacts, not
copied from the run's own summary:

- **GDS**: `chip_top.gds`, 1,616,352 bytes, present at
  `phase3/stage4/gds/chip_top.gds`.
- **Sign-off DRC** (KLayout, `sky130A.lydrc` — the PDK's own sign-off
  deck): re-run FRESH by hand against the shipped GDS (not the run's cached
  report) — `<item>` count in the regenerated report database: **0**.
- **LVS** (netgen, power-aware): run's own report — *"circuits match
  uniquely"* under a power-aware gate netlist (VPWR/VGND/VPB/VNB as top
  ports, per-cell PG connectivity verified on 2,442 instances).
- **STA** (multi-corner OCV sign-off, real post-route SPEF): worst setup
  slack **+4.56 ns** (SS process + max-RC), worst hold slack **+0.38 ns**
  (FF process + min-RC). Both MET.
- **DFT**: Fault ATPG measured stuck-at coverage **100.0%** (scan chain:
  65 internal + 34 boundary cells, covers every flop).
- Confirmed via `flow_compliance_check.py --strict` against the run
  directory: **PASS=36 FAIL=0 MISSING=0**, exit 0.

## What changed since v1.5.65 (this session, plugin v1.9.88→v1.9.94)

Two real plugin defects were found and fixed in the course of this run,
both landed on `main` and independently re-verified before this cell was
generated:

1. **STA_CORNER_BASIS_MISMATCH false-positive (v1.9.93).** The audit's
   per-corner evidence directory (`per_corner/`) is only refreshed
   post-route when a project stages its own liberty override — no default
   run does. The real post-route multi-corner sign-off (this cell's own
   +4.56/+0.38 ns numbers above) lands in `sta_mcorner_ocv.rpt` instead,
   which the audit now also reads. Without this fix every default run's
   `sta_signoff` gate failed regardless of real timing.
2. **Metal-fill engine unreachable in container (v1.9.94).** Not load-
   bearing for THIS cell (sky130A's per-layer density cleared its deck's
   requirements from routing alone — no fill needed, `metal_density.json`:
   met1-met5 all clear, DRC 0 either way) — but the same fix is why the
   gf180mcuD cell of this campaign now reaches 0 DRC violations instead of
   6 density-coverage FAILs. Documented here because both fixes shipped in
   the same session that produced this record.

## Honest scope

**Known, pre-existing, plugin-wide gap — NOT specific to this cell:** the
P0 structural-RTL umbrella invokes 210 of 246 registered checkers; 36 never
run at all (`argparse rejected the umbrella's argv`, e.g. gates requiring
`--rtl-dir`/`--masks`/`--vectors-json` the umbrella does not currently
supply). This is `INCOMPLETE`, not `FAIL`, and does not block
`flow_compliance_check --strict`'s exit code — but it means those 36
checkers' properties are UNCHECKED on this run, same as on every other
current run of the plugin. Not fixed in this session; out of scope for
this record.

**Deferred steps (3, WAIVED):** `rtl_gen` (deterministic program-first
generator, not AI — `serial_parallel_mul_synth.py`, class registered
`rtl_gen=null` so the step itself is waived even though real RTL was
produced), FPGA on-board verify (no DE10 board contract for this class),
and one other machinery-sanctioned deferral per `waivers.json`.

**Provenance note:** the RTL is deterministically generated (program-first,
no LLM) from this cell's own L-docs — sha256-reproducible from the same
input on any host. The design input documents are campaign-shared with the
IHP-SG13G2 and GF180MCU cells of this same campaign round.

One cell (IC × PDK) of the open-PDK matrix. Nothing here is claimed for any
cell other than `spm × sky130A` on plugin v1.9.94.
