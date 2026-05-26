# Vibe-IC End-to-End Result — neorv32

**IC**: neorv32 (NEORV32 RISC-V RV32 microcontroller SoC, platform-independent VHDL)
**Project**: `/home/reyerchu/vibe-ic/benchmark_ic/2nd__neorv32`
**Plugin**: `/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic`
**Container**: `iic-eda` (hpretl/iic-osic-tools) — GHDL 6.0.0-dev, Yosys 0.62 (host 0.33), OpenROAD 26Q1, Magic 8.3.603, KLayout, ngspice/netgen
**Date**: 2026-05-26

---

## FINAL VERDICT

**PARTIAL — routed GDS NOT reached; placed layout reached. NOT DRC/LVS sign-off-clean.**

- **Halted at**: phase3 — detailed routing / GDS stream-out (after a successful synth + placement).
- **Halt reason**: (1) the GHDL-generated neorv32 netlist crashes Yosys's `proc_dlatch` sub-pass on BOTH yosys 0.33 and 0.62 (worked around — see below); (2) after a clean gate netlist + legalized placement, global route stalls on pathological high-fanout nets (clk_i fans out to 213,013 FFs with no CTS; several data nets 88k–91k fanout) because GHDL maps the SoC's IMEM/DMEM/caches to ~213k discrete flip-flops instead of hard macros; (3) honest GDS stream-out is genuinely heavy on a 574k-instance flat top and did not complete within the bounded agent window.

This run **drove the phases in order** (phase1 `--mode docs` → catalog-glue-author → phase2 → phase3) because the top orchestrator's `_need_phase1()` skips phase1 for Path-B raw-docs and phase2 then fails its phase1 precondition (confirmed: first `vibe_ic_one_shot_runner` run gave `phase1 SKIPPED / phase2 FAIL — phase1 precondition unmet`).

---

## Per-Phase Status

### Phase 1 — PASS
- Runner: `phase1_one_shot_runner.py . --mode docs`, rc=0, 201.7s.
- 14/14 L-docs emitted (`phase1/generated_docs/L1..L13.json`), 857 evidence entries, **0 `__TODO__` stubs**, coverage 100.0% (curated 4082/4082).
- L-docs are substantive (L1_DATASHEET ~464KB, L4_REGMAP ~125KB, L8/L9 real port+constant tables). Raster figures skipped (no OCR) — expected.
- Note: L9 extracted top=`neorv32_cpu` (internal CPU from cpu.adoc), not the synthesizable SoC top — handled in phase2 by authoring the real chip-top.

### Phase 2 — FAIL (expected-class FAILs + one real tool crash)
- IC mis-classified as `digital_arithmetic_primitive` (evidence: has_otp; has_fsm; is_pure_digital) — a misclass for a full SoC, but it correctly **WAIVED `rtl_gen`** with `fallback_skill=catalog-glue-author`.
- **catalog-glue-author (AI close-loop)**: catalog had NO neorv32 entry; matched only spurious fragments (fpu_single, spi_master, lfsr, trng, hmac_core, picorv32, ibex) — **all pruned, none is neorv32**. Pulled the genuine upstream neorv32 (BSD-3-Clause, github.com/stnolting/neorv32) and generated the all-Verilog top via **GHDL synthesis** (`make convert`, the canonical `rtl/verilog` auto-conversion) inside iic-eda → `neorv32_verilog_wrapper.v` (82 modules, 80,150 LOC). Authored thin chip-top `neorv32_chip_top.v` (clk_i/rstn_i/uart0_txd_o/uart0_rxd_i) from L1/L9. iverilog `-g2012 -t null` parse of full design = **PASS (exit 0)**. Audit in `plugin_output/declaration.json` (rtl_strategy=catalog_lookup_plus_ai_glue, spdx=BSD-3-Clause).
- phase2 re-run with `--top-name neorv32_chip_top`: `full_stack_tb_gen PASS` (48 L9 ports → 48 DUT pins); `qsf_gen/sdc_gen PASS`.
- Expected-class FAILs (per design class, recorded honestly, no fabricated ports): `reference_tb FAIL` (hardwired AID half-duplex tester TB does not fit a CPU/SoC); `fpga_compile FAIL` (DE10 board pins / SOF); ECO loop → `FAIL_ECO_INERT` (byte-identical RTL — can't auto-ECO a pulled netlist).
- Real issue: `yosys_synth FAIL rc=-11` (segfault) — see root cause below.

### Phase 3 — FAIL (synth FAIL via runner; manually unblocked to placed layout)
- `phase3_one_shot_runner.py` (staged into container mount `/foss/designs/_vibe_2nd_neorv32_p3`, since the repo path is NOT bind-mounted) → **synth FAIL rc=1**.
- Root cause: the runner's synth uses the **yosys-slang** frontend (`plugin -i slang; read_slang ... -DSIMULATION`) which hits an internal assert on the GHDL netlist's escaped identifiers (dots/brackets, e.g. `\neorv32_top_inst.trace_cpu0_o[valid]`):
  `ERROR: Assert 'count_id(wire->name) == 0' failed in kernel/rtlil.cc:2961`.
- Deeper root cause (close-loop bisect, both frontends): the standard yosys frontend ALSO crashes — `proc` segfaults (RC=139) specifically in **sub-pass 4.8 PROC_DLATCH** ("convert process syncs to latches"), reproducible on yosys 0.33 (host) and 0.62 (container), even with a 1 GB stack. The "No latch inferred" notes confirm those signals are NOT real latches.
- **WORKAROUND (non-invasive, no datapath change)**: ran `proc`'s sub-passes manually and **skipped only `proc_dlatch`** (`proc_clean … proc_mux; proc_dff; proc_memwr; proc_clean`). This let synthesis complete. Full ASIC map (flatten → memory_map → techmap → dfflibmap → `abc -liberty` → hilomap → splitnets, sky130_fd_sc_hd, tt_025C_1v80) **RC=0**.

#### Phase 3 backend artifacts
| Item | y/n | Evidence |
|------|-----|----------|
| Gate-level netlist | **YES** | `phase3/stage3/synth/netlist.v` (161 MB) — sky130-mapped |
| Std-cell count | **574,831** cells (incl. **213,012** DFFs) | grep of sky130 instances |
| Synth chip area | **8,339,299 µm² (~8.3 mm²)**, 76% sequential | yosys `stat -liberty` |
| Floorplan DEF | **YES** | `…/pnr/neorv32_chip_top.floorplan.def` (123 MB), die 4600×4600 µm |
| Placed DEF (legalized) | **YES** | `…/pnr/neorv32_chip_top.placed.def` (123 MB) — 574,831 components, 574,834 nets, 2.26M conns, detailed_placement RC=0 |
| Global route | **NO** | stalled on high-fanout nets (clk_i=213,013; data nets to 91,277) — no CTS, memories-as-flops; killed after ~8 min no progress |
| Detailed route | **NO** | not reached |
| GDS (routed) | **NO** | not reached |

#### STA
- **Worst setup slack = −3518.90 ns** at a 20 ns clock (pre-CTS, placement-estimate parasitics, `set_wire_rc` not applied; OpenROAD warned "wire capacitance … is zero"). **This is NOT closed/meaningful signoff timing** — it is a placed, un-CTS'd, no-real-RC estimate on a netlist where memories were expanded to 213k flops with no timing intent. Reported for transparency only.

#### DRC — HONEST (this is the critical part)
- **Attempt 1 (LEF-abstract stream-out)**: Magic `def read` of the placed DEF loaded **REAL geometry** (574,831 subcell instances, bbox 4516.2 × 4575.3 µm = 20.66 mm², 82 child cell types). BUT `gds write` failed: `Error: Cell "sky130_fd_sc_hd__edfxtp_1" is an abstract view; cannot write GDS.` The cells came from LEF abstracts (no internal geometry). Result GDS = **78 bytes**. KLayout independently confirms it is **VACUOUS: top_cells=[], total_cells=0, total_shapes=0**. → Any DRC on this file would report "0 violations" purely because there is no geometry. **This is the documented vacuous-PASS trap and is explicitly NOT a clean signoff.**
- **Attempt 2 (proper stream-out)**: re-ran Magic reading the real cell GDS library (`sky130_fd_sc_hd.gds`, 4.2 MB) FIRST, then the DEF. Magic IS writing **real geometry** ("Generating output for cell neorv32_chip_top"; KLayout sees it writing into `neorv32_chip_top`, record #4,082,040). The single-flush GDS write of a 574k-instance flat top did **not complete within the bounded agent window** (Magic still running at ~27 min, 7 GB RSS, file truncated at 42.5 MB — KLayout: "Unexpected end-of-file … cell=neorv32_chip_top"). So even the proper GDS is **INCOMPLETE**, not signed off.
- **No DRC was run on real geometry** (the only fully-written GDS was the vacuous 78-byte one). **DRC = NOT performed on valid geometry; NOT sign-off-clean.**

#### LVS — WAIVED / not performed
- phase3 runner WAIVED LVS (needs SPICE-extracted netlist + reference; netgen is available but deferred). No LVS run. **LVS = not performed.**

---

## Close-loop actions taken (evidence-based)
1. Drove phase1 explicitly in `--mode docs` after the top orchestrator skipped it (Path-B). → PASS.
2. Invoked `catalog-glue-author`: pruned 7 spurious catalog matches, pulled real BSD-3 neorv32, GHDL-converted to all-Verilog, authored chip-top, iverilog PASS.
3. Bisected the phase3 synth crash to yosys `PROC_DLATCH`; applied a non-invasive workaround (skip only proc_dlatch) → full sky130 synth RC=0.
4. Manually drove OpenROAD floorplan → global placement (converged, overflow→0.0999) → detailed placement (legalized, RC=0) on the 575k-cell netlist.
5. Diagnosed global-route stall to pathological high-fanout (memories-as-flops + no CTS) — honestly recorded as not-routable in this state.
6. Ran BOTH GDS stream-out paths to expose the LEF-abstract vacuous-GDS trap and prove the difference with KLayout shape counts.

## Confirmation real EDA tools ran in iic-eda
GHDL (`make convert`), iverilog (parse), Yosys (synth + bisect), OpenROAD (floorplan/GP/DP/STA/GR), Magic (DEF read + GDS write), KLayout (GDS shape/cell count) — all executed in the `iic-eda` container with real logs under `_vibe_2nd_neorv32_p3/phase3/stage3/pnr/` and `phase2/stage2/synth/`.

## Honest assessment
- **Genuine progress**: real spec extraction (phase1 100% coverage), real OSS RTL integration (not reverse-engineered), real GHDL VHDL→Verilog conversion, real sky130 gate netlist (574k cells / 8.3 mm²), real legalized placement of the full SoC.
- **Routed GDS was NOT reached.** A placed layout is NOT a routed GDS, and **a routed GDS is NOT DRC/LVS sign-off.**
- **DRC/LVS were NOT signed off.** The only completely-written GDS was vacuous (78 bytes, 0 shapes — would have falsely shown 0 DRC). The proper real-geometry GDS write did not finish. No DRC/LVS was performed on valid geometry.
- **Systematic plugin gaps surfaced** (candidates for backlog): (a) SoC-class ICs mis-classified as `digital_arithmetic_primitive`; (b) phase3 slang frontend asserts on GHDL escaped identifiers; (c) yosys `proc_dlatch` segfault on GHDL-generated SoCs needs the skip-dlatch guard built in; (d) GHDL conversion maps on-chip memories to discrete flops → unroutable without macro/`memory_libmap` mapping; the flow needs SRAM macro substitution for memory-bus SoCs.

## Key artifact paths
- Phase1 L-docs: `…/2nd__neorv32/phase1/generated_docs/L*.json`
- Pulled RTL + wrapper: `…/2nd__neorv32/phase2/stage1/rtl/{neorv32_verilog_wrapper.v, neorv32_chip_top.v}`; audit `…/plugin_output/declaration.json`
- Gate netlist: `…/2nd__neorv32/phase3/stage3/synth/netlist.v` (and `phase2/stage2/synth/neorv32_chip_top_synth.v`)
- Placed DEF: `/home/reyerchu/AI_IC_design/_vibe_2nd_neorv32_p3/phase3/stage3/pnr/neorv32_chip_top.placed.def`
- Vacuous GDS (78 B): `…/_vibe_2nd_neorv32_p3/phase3/stage3/pnr/neorv32_chip_top.gds`
- Real-geometry GDS (incomplete): `…/_vibe_2nd_neorv32_p3/phase3/stage3/pnr/neorv32_chip_top.real.gds`
- Reports: `…/2nd__neorv32/reports/phase1_one_shot.json`, `…/reports/orchestrator/phase2_one_shot.json`, `…/_vibe_2nd_neorv32_p3/reports/orchestrator/phase3_one_shot.json`
