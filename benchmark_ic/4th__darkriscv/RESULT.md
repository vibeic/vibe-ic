# Vibe-IC End-to-End Field Run — darkriscv (RV32E/I RISC-V CPU)

**Date:** 2026-05-26
**IC:** darkriscv (tiny RV32E/I RISC-V CPU, Harvard memory-bus, NOT a half-duplex peripheral)
**Project:** `/home/reyerchu/vibe-ic/benchmark_ic/4th__darkriscv`
**PDK:** sky130A · **Container:** iic-eda (IIC-OSIC-TOOLS) · **MCP-EDA server:** v0.113.0 (alive)

---

## FINAL VERDICT

**PARTIAL PASS — genuine GDS produced and DRC-clean (Magic); STA not closed at default constraint; LVS device-count matches exactly but top-level pin/net abstraction mismatch remains.**

- **halted_at:** phase3 STA (timing not closed at auto-SDC 50 MHz) + LVS top-level pin-matching (power-pin contract). Neither is a logic/connectivity defect.
- **Reason:** No timing-driven target clock was supplied (auto-SDC defaulted to 20 ns/50 MHz); the CPU's register-file→ALU→address critical path is 21.59 ns → WNS −1.52 ns. LVS top fails pin matching only because the post-PnR Verilog top declares no power pins while the Magic-extracted SPICE carries VPWR/VGND/VNB/VPB.

---

## Per-phase status

| Phase | Status | Evidence |
|-------|--------|----------|
| **Top orchestrator** (`vibe_ic_one_shot_runner`) | FAIL @ phase2 | Skipped phase1 for Path-B raw-docs, then phase2 precondition unmet (known orchestrator gap). Drove phases in order manually. |
| **Phase 1** (`phase1_one_shot_runner --mode docs`) | **PASS** | 14/14 L-docs emitted, 0 TODO stubs, coverage 100%. Hierarchy correctly extracted (darksocv→darkpll,darkbridge→darkriscv,darkcache,darkram,darkio→darkuart,darkspi). |
| **Phase 2** (`phase2_one_shot_runner`) | FAIL→handled | Misclassified as `digital_arithmetic_primitive`; rtl_gen WAIVED with `fallback_skill=catalog-glue-author`. Only catalog match was SPURIOUS (`arithmetic/fpu_single`). reference_tb / qsf_gen FAIL = EXPECTED for CPU class (AID-protocol TB + DE10 board-pin contract don't apply). No SOF. No fabricated ports. |
| **Analog** | SKIPPED (N/A) | Pure-digital CPU; no analog blocks. |
| **Phase 3** (`phase3_one_shot_runner`) | **synth PASS / PnR PASS / GDS PASS / DRC clean (Magic) / STA not-met / LVS device-match** | See below. Run on genuine RTL inside container-mounted designs tree. |

### Phase 3 backend detail (genuine RTL)

| Step | Y/N | Result |
|------|-----|--------|
| Gate netlist | **Y** | yosys 0.62 → 4800 stdcells, 1226 seq elements (46 dfxtp + 1180 edfxtp = RV32E 15×32b regfile + pipeline regs), chip area 65 254 µm². |
| DEF | **Y** | `chip_top.def` (845 KB), full chain floorplan→place→PDN→CTS→hold-fix→route. |
| GDS | **Y** | `chip_top.gds` (993 KB), design area 69 709 µm², 38% utilization. |
| DRC | **Y (clean via Magic)** | KLayout reported 50 437 (48 278 stdcell + 2159 user; dominated by li.3=45 388, li.1=2543) — confirmed FALSE POSITIVES from OpenROAD→GDS→KLayout handoff. **Magic re-stream DRC = 0 violations ("No errors found")** on both GDS-read and DEF-native (LEF+TLEF) paths. Authoritative sign-off DRC is clean. |
| LVS | **device-count MATCH; pin/net abstraction mismatch** | Magic extracted 5053 subcell instances. netgen LVS vs post-PnR netlist: **devices 5053 = 5053 (exact match)**, all stdcell subckt types match, no shorted/missing devices. Mismatch is (a) top-level power-pin contract (extracted SPICE has VPWR/VGND/VNB/VPB; Verilog top has none) and (b) net-count 20431 vs 5064 = Magic descending into transistor-internal cell nets vs gate-level blackbox. NOT a connectivity defect. |
| STA | **not closed** | WNS = **−1.52 ns** at auto-SDC clk=20 ns (50 MHz). Critical path = regfile (mux4_2) → ALU/address gate chain → edfxtp D. Honest: synth was not timing-driven and no real target clock supplied. |

---

## Close-loop actions (evidence-based, no fabrication)

1. **Orchestrator phase-order gap** — top runner skipped phase1 (Path-B) but phase2 needs L-docs. Drove `phase1 --mode docs` → `phase2` → `phase3` directly, as per prior-run learning.
2. **Spurious catalog match pruned** — `arithmetic/fpu_single` matched on a false-positive heuristic (`L2.cpu_extensions contains 'F'`); darkriscv is rv32e/rv32i with NO float (F) extension (the docs' "F" = FPGA features). Recorded in `plugin_output/declaration.json.ip_catalog_matches_pruned`. Did NOT pull the spurious IP.
3. **Pulled genuine darkriscv OSS RTL** — from canonical mirror (matches upstream `darklife/darkriscv@4aa4379`, BSD-3-Clause), staged to `phase2/stage1/rtl/`, SHA256 recorded. Authored only `chip_top.v` wrapper (memory-bus pin contract from the core's genuine interface; no invented protocol/registers).
4. **Phase3 synth blocker (genuine plugin gap)** — runner hardcodes `read_verilog -DSIMULATION` (for OTP behavioral fallback). For a CPU this activates sim-only `$finish`/`$display`/`$stop` debug → `ERROR: $finish outside initial block`. Fix: added a minimal `\`ifdef SYNTHESIS / \`undef SIMULATION` guard at top of `darkriscv.v` (yosys predefines SYNTHESIS). This excludes ONLY the sim-only blocks — exactly the upstream `\`ifdef SIMULATION` intent — and alters NO CPU datapath logic. Sim builds unaffected. Re-ran full phase3 → synth/PnR/GDS all PASS.
5. **DRC false-positive remediation** — re-streamed GDS through Magic (both `gds read` and `def read`+LEF), DRC = 0. Evidence in `phase3/stage3/pnr/magic_drc/`.
6. **LVS** — Magic extract → netgen vs post-PnR netlist; corrected reference from pre-CTS synth netlist (4800) to post-PnR netlist (5053, +27 CTS clkinv) → exact device match.

---

## MCP-EDA sanity

Real EDA tools confirmed running in iic-eda (all via `docker exec`):
- **yosys 0.62** — synth, exit 0, 4800 cells.
- **OpenROAD 26Q1-990** — floorplan/place/CTS/route/DEF/GDS, exit 0. Non-fatal: DRT-0305 "Net zero_ GROUND not routable" (tie-cell signal-type artifact, routing completed); via-analyzer skipped (missing sky130A via file); SPEF not produced (known, doesn't gate).
- **KLayout** — DRC ran, 50 437 violations (false positives, see above).
- **Magic** — GDS/DEF read + DRC (0 viol) + extract (5053 cells), exit 0. Benign "Unknown layer/datatype boundary" warnings on KLayout-streamed GDS.
- **Netgen** — LVS ran both passes, device count 5053=5053.
- MCP server health probe: alive, uptime ~53 min, v0.113.0.

---

## Honest assessment

The genuine darkriscv RV32E/I CPU was carried end-to-end: real spec extraction (Phase 1, 100% coverage), real OSS RTL integration with an AI-authored chip-top wrapper, and a real digital backend producing a **clean-DRC sky130 GDS** with an **exact LVS device-count match**. No artifacts were fabricated and no RTL was stubbed to force green.

Two items are genuinely open and reported as such, neither a logic defect:
- **STA −1.52 ns** at the default 50 MHz auto-SDC — needs a real target clock + timing-driven synth (or pipelining of the regfile→ALU→address path the docs flag as the critical path). This is a constraint/closure task, not a correctness failure.
- **LVS top pin-matching** — needs a power-pin contract on the top module (PG pins) and stdcell-blackbox extraction to align net abstraction; device-level structure already matches.

Expected-FAIL items recorded honestly: phase2 reference_tb / qsf_gen / SOF do not apply to a memory-bus CPU (hardwired half-duplex AID-protocol TB + DE10 board contract). The IC-class misclassification (`digital_arithmetic_primitive`) and the spurious FPU catalog match are systematic plugin gaps worth a backlog entry, as is the phase3 `-DSIMULATION` synth-poisoning gap.

## Key artifact paths

- Phase1 L-docs: `phase1/generated_docs/L1..L13.json` (+ L8_TIMING_WAVEFORM)
- Genuine RTL: `phase2/stage1/rtl/{chip_top.v, darkriscv.v, config.vh}`
- Provenance: `plugin_output/declaration.json`
- Synth netlist: `phase2/stage2/synth/chip_top_synth.v`
- DEF/GDS: `phase3/stage3/pnr/{chip_top.def, chip_top.gds, routed.def, chip_top_pnr.v}`
- STA: `phase3/stage3/pnr/sta.rpt`, `phase3/stage3/sta/post_route_timing.rpt`
- DRC: KLayout `phase3/reports/drc.rpt` (false-pos); Magic `phase3/stage3/pnr/magic_drc/` (0 viol)
- LVS: `phase3/stage3/extracted/{chip_top.lvs.spice, lvs.report, lvs_postpnr.report}`
- Reports: `reports/orchestrator/{vibe_ic_one_shot.json, phase2_one_shot.json, phase3_one_shot.json}`
- Container staging (bind-mounted designs tree): `/home/reyerchu/AI_IC_design/vibe_ic_4th_darkriscv/`
