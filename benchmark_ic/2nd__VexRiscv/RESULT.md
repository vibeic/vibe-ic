# Vibe-IC Field Run — VexRiscv (RV32I CPU core)

**Date:** 2026-05-26
**Project:** `/home/reyerchu/vibe-ic/benchmark_ic/2nd__VexRiscv`
**IC name:** VexRiscv
**Top module (silicon):** `chip_top` (thin wrapper) → `VexRiscv` (real RV32I core)

---

## VERDICT: PARTIAL — RTL exists, synth + routed GDS reached, NOT sign-off-clean

Previously this project was **BLOCKED** on the SpinalHDL→Verilog toolchain. That
blocker is **resolved**: `VexRiscv.v` was generated for real inside the `iic-eda`
container via `sbt "runMain vexriscv.demo.GenSmallest"` (SpinalHDL 1.13.0). The
flow now runs end-to-end on genuine RTL.

New verdict is **PARTIAL**, not PASS:
- Phase 1: PASS (14 L-docs, 100% coverage).
- Phase 2: synth PASS on the real core; reference_tb / qsf_gen / SOF gates FAIL —
  the **expected CPU-class half-duplex-AID-TB mismatch** (TB wants reset_n / id_bus /
  USB-HID; a CPU memory-master bus has no ports to bind it). Recorded honestly, no
  ports fabricated.
- Phase 3: synth → PnR → CTS → route → **routed GDS reached**, but timing is
  VIOLATED and DRC is NOT sign-off-clean. Routed GDS reached ≠ signed off.

---

## Per-phase status

### Phase 1 — Doc extraction (PASS)
- 14 L-docs in `phase1/generated_docs/` (L1–L13, incl. split L8 timing/constants).
- NOTE: `L9_INTEGRATION_SPEC.json` carries an `ic_name`/`GCD` top-module **fallback**
  (`top_ports = []`) because the input docs predate the generated Verilog and
  contained no module declaration. The **authoritative port contract is the actual
  `VexRiscv.v` port list**, which `chip_top.v` re-exposes 1:1.

### Phase 2 — RTL + synth + TB (synth PASS; TB FAIL = expected)
- **`phase2/stage1/rtl/VexRiscv.v`** — GENUINE Verilog, 3346 lines,
  sha256 `ca751c1764bf68a9e4a53fa51626fc15b9d780fae2417ba8cc85023d12342b20`.
  Generated via SpinalHDL 1.13.0 / sbt `vexriscv.demo.GenSmallest` in `iic-eda`.
  Top module `VexRiscv` + `StreamFifoLowLatency` + `StreamFifo` submodules.
  Real RV32I core: 5-stage pipeline, 32×32 regfile (1024 memory bits), IBusSimple +
  DBusSimple memory-master interfaces, 3 interrupt inputs. NOT modified.
- **`phase2/stage1/rtl/chip_top.v`** — thin authored wrapper (NEW). Instantiates one
  real `VexRiscv`; forwards iBus(cmd/rsp) + dBus(cmd/rsp) + timer/external/software
  interrupts + clk + active-high reset 1:1. No datapath logic. Nothing pruned
  (single real core). `VexRiscv.v` untouched.
- **lint/parse:** host `iverilog -g2012 chip_top.v VexRiscv.v` → exit 0, no warnings.
  Top `chip_top` elaborates clean. Yosys reads full hierarchy
  chip_top → VexRiscv → StreamFifoLowLatency → StreamFifo.
- **yosys_synth: PASS** — `phase2/stage2/synth/netlist_yosys.v`, synth_top=`chip_top`.
  Runner pre-techmap cells=6083; post-abc gate-level = 15859 cells
  (1644 DFFs, 8521 NAND, 5090 NOR, 604 NOT). No latches inferred.
- **reference_tb: FAIL** (iverilog rc=2 against `aid_class_reference_tb`) — EXPECTED.
  The AID-class TB drives a half-duplex/USB-HID `id_bus` protocol + loads
  `apple.hex`/`otp_image.hex`; a CPU mem-bus exposes no `reset_n`/`id_bus`/HID ports
  to bind. **No ports fabricated to force a bind.**
- **qsf_gen: FAIL** (rc=1, "no port→board-pin mapping; Top 'GCD' ports do not match
  board") and **fpga_compile / SOF: SKIP** — same CPU-class mismatch. No SOF produced.
- ECO loop declared `FAIL_ECO_INERT` (byte-identical RTL; nothing remediable) — honest.

### Phase 3 — Backend (synth → PnR → GDS reached; timing + DRC NOT clean)
Ran via `phase3_one_shot_runner.py` on the genuine RTL, STAGED inside the container
mount at `/foss/designs/_vex2nd_p3` (host `/home/reyerchu/AI_IC_design/_vex2nd_p3`;
the repo path is NOT bind-mounted into `iic-eda`). PDK = sky130A, top = `chip_top`.
Plain Verilog — no sv2v needed.

- **synth: PASS.** sky130_fd_sc_hd mapping. Standalone verification with the runner's
  hardcoded `-DSIMULATION` confirmed it does **NOT poison synth** — VexRiscv.v's two
  `` `ifndef SYNTHESIS `` blocks are dead debug-string regs (enum→ASCII for waveforms,
  never read by datapath); yosys prunes them. No SYNTHESIS guard was needed (and none
  added — defines don't carry across the runner's per-file `read_verilog` calls; the
  gate-level netlist handed to OpenROAD contains no `ifdef` blocks anyway).
  Pre-layout chip area (sky130 hd) ≈ 76797 µm².
- **pnr: PASS.** `chip_top.def`, real floorplan/PDN/CTS/route. **6964 placed std cells**
  (DEF `COMPONENTS 6964` == post-PnR netlist 6964, exact match). 7029 nets, 180 pins.
  Design area 81357 µm², 36% utilization, die bbox 509×509 µm.
  CTS: TritonCTS, clk net with **1644 sinks**, avg sink wire 620 µm.
- **gds: PASS.** `chip_top.gds` = 1,223,138 bytes.
- **STA: VIOLATED.** At 20 ns (50 MHz) clock:
  - **WNS = -29.08 ns (setup VIOLATED)** — worst path is a single-cycle combinational
    chain through the VexRiscv decode/ALU/mux logic (data arrival 49.37 ns >> 20.29 ns
    required). Far too long for 50 MHz; a CPU core needs a realistic target / retiming.
  - Recovery on reset = +18.67 ns (MET).
  - **No hold violations** (OpenROAD RSZ-0033: "No hold violations found").
  - Timing **NOT met**. Reports: `phase3/reports/sta.rpt`,
    `phase3/stage3/sta/post_route_timing.rpt`.
- **DRC — HONEST (NOT sign-off-clean):**
  - DRC was run by **KLayout 0.30.6** (`sky130A.lydrc` runset), **NOT Magic**.
    The Magic "`gds read` drops cell-internal geometry → vacuous 0 DRC" trap does
    **NOT** apply to this run — Magic was never invoked.
  - **Verified the GDS holds REAL geometry** (independent KLayout reload):
    1 top cell `chip_top`, 77 cells, **76 sky130 std-cell master defs**,
    **10,724 real shapes across 37 layers**, bbox 509×509 µm; example
    `sky130_fd_sc_hd__xor2_1` has 112 internal shapes. Geometry is NOT empty/abstract.
  - **DRC = 56,415 violations (REAL, non-vacuous)** — user=1397, stdcell=55018.
    Top rules: li.3 (li spacing) = 51,365; li.1 (li width) = 2,983; m1.2 = 736;
    li.5 = 670; ct.2 = 46. DRC items carry real micron edge-pair coordinates
    (e.g. `edge-pair: (436.945,321.725;...)`). Report: `phase3/reports/drc.rpt`.
    The li-layer storm is a systematic stream-out artifact (sky130 cell GDS merged
    into a routed layout that was never run through a Magic/Calibre fill + sign-off
    pass). **NOT sign-off-clean.**
  - OpenROAD's own detailed-route DRC: 1 router-internal violation, "DRC clean: NO".
- **LVS: WAIVED (honest).** Parasitic extraction did not produce a SPICE/SPEF netlist
  (`OpenROAD RCX-0134: no extraction data` — global_route parasitics not estimated),
  so there is no extracted netlist for a true device-level netgen LVS.
  netgen 1.5.316 IS available. **Device-count cross-check performed honestly:**
  the post-PnR netlist and the routed DEF have **identical per-cell-type histograms**
  (76 cell types, 6964 instances; e.g. 1425 edfxtp_1, 1285 nor2_1, 1272 o21ai_0 all
  match exactly) — netlist↔layout instance consistency holds. This is NOT a full
  SPICE LVS; true LVS remains deferred.

---

## Real EDA tools that ran in `iic-eda` (hpretl/iic-osic-tools:latest)
- **SpinalHDL 1.13.0 / sbt** — generated `VexRiscv.v` (GenSmallest).
- **Yosys 0.62** — RTL→gate synth (sky130_fd_sc_hd).
- **OpenROAD 26Q1-990-g15af3a5c0** — floorplan, PDN, TritonCTS, global+detailed route,
  STA, DEF; routed real CPU nets (e.g. `u_vexriscv.decode_INSTRUCTION_ANTICIPATED[17]`,
  491 pins) — confirms the genuine core was routed, not a stub.
- **KLayout 0.30.6** — GDS stream-out (stream_out.py, LEF+cell-GDS merge) + DRC.
- **Netgen 1.5.316** — available; device-count cross-check (full LVS deferred).
- Tool errors/notes: EST-0005/RCX-0134 (no SPEF — parasitics not estimated → LVS
  waived); DRT-0120 large-net warnings (expected for wide CPU decode/regfile fanout);
  via-analyzer skipped (missing PDK file). All recorded; none fabricated.

---

## Key artifact paths
- RTL: `phase2/stage1/rtl/VexRiscv.v`, `phase2/stage1/rtl/chip_top.v`
- Synth netlist (phase2): `phase2/stage2/synth/netlist_yosys.v` + `yosys.log`
- DEF (routed): `phase3/stage3/pnr/routed.def` / `chip_top.def`
- PnR netlist: `phase3/stage3/pnr/chip_top_pnr.v`
- GDS: `phase3/stage3/pnr/chip_top.gds`, `phase3/stage4/gds/chip_top.gds`
- STA: `phase3/reports/sta.rpt`, `phase3/stage3/sta/post_route_timing.rpt`
- DRC (KLayout): `phase3/reports/drc.rpt`
- OpenROAD log: `phase3/stage3/pnr/openroad.log`
- Container staging (source of phase3 run): `/foss/designs/_vex2nd_p3`
  (host `/home/reyerchu/AI_IC_design/_vex2nd_p3`)

---

## Honest assessment
The SpinalHDL toolchain blocker is gone and the flow runs end-to-end on a **genuine,
non-stubbed RV32I VexRiscv core**. Phase 1 (14 L-docs), Phase 2 synth (15859 gates),
and Phase 3 synth→PnR→route→GDS (6964 placed cells, routed GDS with verified real
geometry) all completed with real EDA tools in `iic-eda`.

It is **NOT tapeout-ready**:
1. **Timing fails** — WNS -29.08 ns at 50 MHz (single-cycle combinational CPU path);
   needs a realistic clock target and/or pipelining/retiming.
2. **DRC fails** — 56,415 REAL (KLayout, non-vacuous) violations, dominated by li-layer
   spacing inside the streamed std cells; needs a proper Magic/Calibre fill + sign-off
   pass. This is **not** the vacuous-0 Magic trap (Magic wasn't used; geometry verified
   present).
3. **LVS not done** — extraction produced no SPICE netlist; only an instance-count
   cross-check (netlist == DEF, exact) was possible. True device-level LVS deferred.
4. The Phase-2 reference_tb / SOF FAILs are the **expected** CPU-class vs
   half-duplex-AID-TB mismatch, recorded without fabricating ports.

**Routed GDS reached ≠ signed off.** Verdict: PARTIAL.
