# Vibe-IC Field Run — VexRiscv (RV32I CPU core)

- **Project:** `/home/reyerchu/vibe-ic/benchmark_ic/4th__VexRiscv`
- **IC:** VexRiscv (RISC-V RV32I, SpinalHDL-generated Verilog)
- **Date:** 2026-05-26
- **Plugin root:** `/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic`
- **Container:** `iic-eda` (sky130A PDK, OpenROAD / Yosys / Magic / KLayout / netgen / OpenSTA)

## FINAL VERDICT: ROUTED GDS REACHED — NOT SIGN-OFF CLEAN

The earlier BLOCKED verdict is **rescinded**: the SpinalHDL→Verilog blocker
was resolved out-of-band (`sbt "runMain vexriscv.demo.GenSmallest"`,
SpinalHDL 1.13.0), so genuine `VexRiscv.v` now exists on disk. The full
digital flow now reaches a **placed-and-routed GDS** of the real CPU core.
It is **not signed off**: STA setup timing is VIOLATED at the runner's
default clock, and KLayout DRC reports 56,415 real geometry violations.
Nothing was fabricated; all failures are recorded verbatim.

## Phase 1 — DONE (PASS) — unchanged

- 14/14 L-docs in `phase1/generated_docs/L*.json` (L1–L13 + L8_TIMING_WAVEFORM), 100% coverage, 0 stubs.
- Note: L9_INTEGRATION_SPEC is noisy/imperfect (carries GCD-peripheral remnants, `top_module="GCD"`); the authoritative port list came directly from the real `VexRiscv.v` module header.

## Phase 2 — RTL EXISTS + SYNTH PASS; CPU-class TB FAIL (EXPECTED)

- **`VexRiscv.v`** = genuine Verilog, 3346 lines, sha256 `ca751c17…`.
  Top `module VexRiscv` with IBus master (`iBus_cmd_*`/`iBus_rsp_*`),
  DBus master (`dBus_cmd_*`/`dBus_rsp_*`), 3 interrupt inputs, `clk`/`reset`;
  submodules `StreamFifo` / `StreamFifoLowLatency`. No checked-in RAM (clean for PnR).
  Generated via SpinalHDL/sbt in iic-eda (NOT modified by this run).
- **`chip_top.v`** (authored this run, `phase2/stage1/rtl/chip_top.v`) = thin
  1:1 pass-through wrapper instancing `VexRiscv` and exposing IBus/DBus +
  interrupt/clk/reset at the chip boundary. No datapath logic, no RAM, no muxing.
- **iverilog `-g2012` parse: CLEAN** (chip_top + VexRiscv, rc=0).
- **Yosys synth (runner, in iic-eda): PASS** — `synth_top=chip_top`,
  netlist `phase2/stage2/synth/netlist_yosys.v` (1.9 MB). Host-side generic
  synth corroborates: ~6233 cells inside the VexRiscv module (1061+302 DFFE
  flops, 2765 muxes, ALU XOR/AND tree) — genuine RV32I datapath, not a stub.
  Flattened gate netlist retains 5977 VexRiscv-internal signal names
  (IBusSimplePlugin, RegFilePlugin, …).
- **`reference_tb`: FAIL (EXPECTED, CPU-class mismatch).** The AID-class
  half-duplex reference TB (`tools/protocol_tb/aid_class_reference_tb.v`)
  instances the DUT with ports `reset_n` and `id_bus` (USB-HID / half-duplex
  protocol IC). A CPU memory-bus top has neither →
  *"port `reset_n` is not a port of u_dut / port `id_bus` is not a port of u_dut"*.
  No ports were fabricated to satisfy the TB.
- **`qsf_gen`: FAIL (EXPECTED).** No port→board-pin mapping resolvable —
  CPU IBus/DBus master pins don't match the DE10-Lite board definition.
- **`rtl_gen`: WAIVED** (RTL pre-supplied, not generated). SDC + manifests PASS.
- Phase-2 runner overall verdict: **FAIL** (driven by reference_tb/qsf_gen —
  the expected CPU-vs-protocol-TB impedance mismatch).

## Phase 3 — synth → PnR → routed GDS (staged in container mount)

Staged at host `/home/reyerchu/AI_IC_design/_vex4th_p3` = container
`/foss/designs/_vex4th_p3` (the repo path is NOT bind-mounted into iic-eda).
Plain Verilog (no sv2v). top = `chip_top`, pdk = sky130A.
**No `-DSIMULATION` guard injection needed** — `VexRiscv.v` already wraps its
only sim-only blocks (SpinalHDL enum→string mirror regs) in `` `ifndef SYNTHESIS ``;
synth defines `SYNTHESIS` and excludes them. No datapath change made.

| Step | Tool | Status | Result |
|------|------|--------|--------|
| synth | Yosys 0.33 | PASS | `chip_top_pnr.v` = **6964 std-cell instances** |
| pnr | OpenROAD | PASS | floorplan→place→CTS→route; DEF emitted; 1644 clock sinks (flops) |
| gds | OpenROAD stream_out | PASS | `chip_top.gds` 1,223,138 B, sha256 `f933efea…` |
| sta | OpenSTA | (in pnr) | **WNS = −29.08 ns VIOLATED** (setup) |
| drc | KLayout sky130A.lydrc | FAIL | **56,415 violations** |
| lvs | netgen | WAIVED | structural cross-check done (see below) — NOT signed off |

- **PnR (OpenROAD, genuine):** 6708 placed instances, 180 I/O, core area
  227,937 µm², util 36.5%, 1644 CTS clock sinks. **Device-count cross-check:
  routed netlist 6964 = DEF `COMPONENTS 6964` (exact match)**, no dropped/added cells.
- **STA — HONEST: TIMING NOT MET.** At the runner's default 20 ns clock (50 MHz),
  worst setup path (FF→ALU/mux datapath→FF) has data arrival 49.37 ns vs required
  20.29 ns → **WNS −29.08 ns, VIOLATED**. (A reset recovery path is MET at +18.67 ns.)
  This is real negative slack from an un-budgeted aggressive clock on an
  unoptimized CPU core — NOT a vacuous PASS. `phase3/stage3/pnr/sta.rpt`.

### DRC — HONEST (geometry-load verified)
- **KLayout DRC = real, substantively NON-clean:** 56,415 violations
  (1,397 routing/user + 55,018 std-cell-internal); top rules li.3=51,365,
  li.1=2,983, m1.2=736, li.5=670. KLayout loaded **full geometry** (verified:
  top cell `chip_top`, 77 cells, 37 layers, bbox 509×509 µm, **10,724 shapes**),
  so this count reflects real polygons. The 55k std-cell-internal hits come from
  streaming GDS out of LEF abstracts (cell-internal layers conflict with the
  sign-off rule deck) — i.e. this GDS is NOT a sign-off-clean layout.
- **Magic `gds read` = VACUOUS, confirmed empirically.** Re-reading the same
  GDS in Magic with `sky130A.tech` threw **467 "Unknown layer/datatype in
  boundary" errors** (layers 1/2/3/8/9 across every std cell) — Magic **DROPPED
  the cell-internal geometry**. A `drc check` on those emptied abstracts would
  report ~0 violations = a VACUOUS clean, NOT sign-off. **The honest DRC signal
  is the KLayout 56,415, not any Magic "0 DRC".**

### LVS — HONEST: NOT signed off
- Runner WAIVED LVS (needs SPICE-extracted netlist + reference). A true
  layout-extracted LVS is **not achievable here** because Magic dropped the
  GDS geometry (above), so no real device-level extraction exists.
- Structural cross-check done with netgen (`phase3/netgen_lvs_struct_xcheck.out`):
  synth gate netlist vs routed gate netlist → device classes reported
  *equivalent*, but **top-level "failed pin matching"** on a handful of
  reset/floating rsp pins (`iBus_rsp_payload_error`, `iBus_rsp_payload_inst[0:1]`,
  clk alias) — a netgen Verilog-vs-Verilog pin-list quirk on black-box leaf
  cells, NOT a transistor-level LVS. **LVS is NOT signed off.**

## EDA tools that actually ran (in iic-eda)

- Yosys 0.33 (synth, both phases) — real netlists + stat logs.
- OpenROAD (floorplan/place/CTS/route/stream_out) — `openroad.log`, DEF set, GDS.
- OpenSTA (timing) — `sta.rpt`, `post_route_timing.rpt`.
- KLayout (DRC + geometry/shape audit) — `drc.rpt` (16.5 MB), 10,724-shape count.
- Magic 8.3 (geometry-load cross-check) — 467 Unknown-layer drops (vacuity proof).
- netgen 1.5 (structural LVS cross-check) — `netgen_lvs_struct_xcheck.out`.
- iverilog (g2012 parse of wrapper+core) — clean.

## Key artifact paths

- RTL: `phase2/stage1/rtl/VexRiscv.v` (sha `ca751c17…`), `phase2/stage1/rtl/chip_top.v`
- Synth: `phase2/stage2/synth/netlist_yosys.v`
- PnR/GDS: `phase3/stage3/pnr/{routed.def,post_cts.def,post_hold.def,chip_top.gds,chip_top_pnr.v,openroad.log,sta.rpt}`
- GDS handoff: `phase3/stage4/gds/chip_top.gds` (sha `f933efea…`)
- DRC: `phase3/reports/drc.rpt` (KLayout, 56,415 viol)
- STA: `phase3/reports/sta.rpt` (WNS −29.08 ns)
- LVS cross-check: `phase3/netgen_lvs_struct_xcheck.out`
- Orchestrator: `phase3/phase3_one_shot.json`

## Integrity statement

`VexRiscv.v` is the genuine SpinalHDL-elaborated RV32I core (unmodified).
`chip_top.v` is a pure pass-through wrapper (no datapath). The Phase-2
reference_tb/qsf_gen failures are the expected CPU-vs-protocol-TB mismatch,
recorded verbatim with no fabricated ports. Phase-3 reached a real routed GDS,
but is **NOT sign-off clean**: STA setup is VIOLATED (−29.08 ns) and KLayout
DRC = 56,415 real violations. The Magic "0 DRC" trap was checked and
explicitly rejected (467 Unknown-layer drops = vacuous). LVS is NOT signed off.
