# Vibe-IC End-to-End Run — darkriscv (RV32I/E RISC-V SoC)

**Date:** 2026-05-26
**IC:** darkriscv (DarkSoCV) — open-source RV32I/E RISC-V CPU SoC (darklife/darkriscv)
**Project:** `/home/reyerchu/vibe-ic/benchmark_ic/2nd__darkriscv`
**Container:** `iic-eda` (hpretl/iic-osic-tools)
**PDK:** sky130A (sky130_fd_sc_hd)

---

## FINAL VERDICT: PARTIAL PASS — halted at Phase 3 detailed-route DRC convergence (BLOCKED, irreducible within budget)

Phase 1 PASS · Phase 2 RTL genuine + synthesizable (phase2 runner verdict FAIL = expected half-duplex-model mismatch, NOT a design defect) · Phase 3 synth/floorplan/place/CTS/global-route/**timing MET** + GDS generated, but **detailed-route did not converge to a DRC-clean layout** within the 600 s OpenROAD budget, and post-PnR routed netlist was therefore not emitted → **LVS BLOCKED**.

No artifact was fabricated. No RTL was stubbed. The genuine open-source darkriscv RTL was pulled under BSD-3-Clause and carried all the way to a real routed DEF + GDSII via real EDA tools.

---

## halted_at + reason

- **halted_at:** phase3 — `detailed_route` (TritonRoute)
- **reason:** The behavioral `darkram` (unified RAM as a flat flop array) plus dual L1 caches produce a register-heavy netlist whose detailed routing does not converge to DRC-clean within the 600 s per-call OpenROAD budget. At MLEN=13 (8 kB) the design is intractable (67k-degree read-mux nets → global-route timeout). Reduced to MLEN=8 (256 B, a sanctioned design parameter) the design routes but TritonRoute leaves ~16k–18k DRC violations (mostly met1 shorts) that persist independent of utilization (tried 44%/24%/22%/20%) and time out before optimization closes. Upstream `openroad_README.md` itself flags that `darkram` should be a hard SRAM macro (future work) — i.e. this is a known design-maturity gap, not a flow error.

---

## Per-phase status

| Phase | Status | Notes |
|-------|--------|-------|
| **Phase 1 (L1–L13)** | **PASS** | 14 L-docs emitted, 0 `__TODO__` stubs, 100% curated coverage. `class_path=processor_cpu`, top=`DarkSoCV`, full submodule hierarchy, clk 75 MHz / 13.33 ns. (cosmetic defect: `ic_name="SHA256"` stale default — description+vendor correctly identify DarkRISCV/darklife.) |
| **Phase 2 (RTL→SOF→ref-TB)** | **FAIL (expected)** | Runner verdict FAIL. `rtl_gen` WAIVED → catalog-glue-author. `reference_tb`/`usb_hid_tester`/`qsf` board-pin FAIL = **half-duplex AID-peripheral model applied to a memory-bus CPU** (L3 confirms `half_duplex != True`, no opcodes). Genuine RTL pulled + verified synthesizable. NOT a design defect. |
| **Analog** | **SKIPPED** | No analog blocks (pure digital CPU). |
| **Phase 3 (synth→PnR→GDS→DRC→LVS)** | **PARTIAL** | See artifact table. |

### Phase 3 backend artifact checklist

| Step | Produced? | Tool | Detail |
|------|-----------|------|--------|
| Synthesized netlist | **YES** | Yosys 0.33/0.62 | `phase3/stage3/synth/netlist_darksocv.v` — 11,939 sky130_fd_sc_hd cells (MLEN=8), real gate map. (MLEN=13 full build also synthesizes clean: 205,813 cells / 2.92 mm².) |
| Floorplan / Place | **YES** | OpenROAD | 22–44% util, real placement. |
| CTS | **YES** | OpenROAD | clkbuf tree inserted. |
| **STA / timing** | **YES — MET** | OpenROAD | slack **+0.67 to +1.44 ns at 75 MHz** (target 13.33 ns) — **timing closed**. |
| Global route | **YES** | OpenROAD/FastRoute | completed. |
| Routed DEF | **YES (with violations)** | OpenROAD | `phase3/stage3/pnr/darksocv.def` — 52,632 routed met/li segments, but ~16–18k DRC viols (8.5k met1 shorts) unresolved at timeout. |
| Post-PnR routed netlist | **NO** | — | route timed out before `write_verilog` → blocks structural LVS. |
| GDSII | **YES** | KLayout 0.30.6 | `phase3/stage4/gds/darksocv.gds` — real GDSII v2.88, 8.6 MB, 558 cells (446 lib + DEF merge). |
| **DRC** | **INCONCLUSIVE** | KLayout | KLayout sky130 deck returns `DRC_COMPLETE=YES`/PASS, but the source DEF carries TritonRoute met1 shorts → KLayout PASS is **not a trustworthy clean signal** (cell-abstract geometry vs route shorts). Reported honestly as NOT DRC-clean. |
| **LVS** | **NO (BLOCKED)** | netgen avail | No converged post-PnR netlist to compare; yosys_equiv attempted but `routed.v` absent (route timeout). |

---

## Key artifact paths (canonical project)

- L-docs: `phase1/generated_docs/L1..L13.json` (+ L8_TIMING_WAVEFORM)
- Genuine RTL: `phase2/stage1/rtl/{darksocv,darkbridge,darkriscv,darkcache,darkram,darkio,darkuart,darkpll}.v` + `config.vh`
- Firmware boot image: `phase2/stage2/src/darksocv.mem` (genuine 1991-word RV32 image)
- Provenance/audit: `plugin_output/provenance.jsonl`, `plugin_output/declaration.json`
- Synth netlist: `phase3/stage3/synth/netlist_darksocv.v`
- Routed DEF: `phase3/stage3/pnr/darksocv.def`
- GDSII: `phase3/stage4/gds/darksocv.gds`
- Reports: `reports/orchestrator/{phase2,phase3}_one_shot.json`
- Working copy (under container mount, used for in-container EDA): `/home/reyerchu/AI_IC_design/2nd__darkriscv_p3/`

---

## MCP-EDA sanity — real tools ran in iic-eda

| Tool | Version | Used for | Exit |
|------|---------|----------|------|
| Yosys | 0.33 (host) / 0.62 (container) | synth → netlist | 0 (clean) |
| OpenROAD | 26Q1-990-g15af3a5c0 | floorplan/place/CTS/route/STA | 0 for place/CTS/GR/STA; **detailed_route timed out at 600 s with DRC viols** |
| KLayout | 0.30.6 | GDS merge + DRC | 0 (GDS real; DRC PASS but inconclusive vs route shorts) |
| Netgen | 1.5.316 | LVS (available, not exercised — no routed netlist) | n/a |
| Icarus | 13.0 | RTL parse sanity | 0 |

Errors of note: `DRT-0305` (tie-net mis-flagged POWER) — **resolved** via `setundef -zero` + `hilomap`; `DRT-0199` ~16–18k route DRC violations + 600 s timeout — **unresolved (irreducible blocker)**.

---

## Close-loop actions taken (honest log)

1. **Top orchestrator skipped phase1** (Path-B docs) → ran `phase1_one_shot_runner.py --mode docs` explicitly. PASS (14 L-docs, 100% coverage).
2. **phase2 arg fix:** runner uses `--top-name` not `--ic-name`; re-ran with `--top-name darksocv`.
3. **rtl_gen WAIVED + spurious catalog match:** the only IP match was `arithmetic/fpu_single` (conf 0.50, matched on an `F` ISA token) — **pruned as spurious** (darkriscv is integer RV32I/E, no FPU; no darkriscv catalog entry exists). Per catalog-glue-author, **pulled genuine open-source darkriscv RTL** from `darklife/darkriscv@4aa4379` under **BSD-3-Clause** (permissive, passes license gate); wrote provenance + declaration. darksocv.v is itself the integration top → no separate wrapper needed; ASIC-clean config uses no board define so the darkpll vendor PLL primitive path is bypassed (`assign CLK=XCLK`).
4. **yosys `$readmemh` fail:** placed genuine `darksocv.mem` boot image at the path the RTL expects.
5. **yosys `$finish outside initial` fail:** root-caused to the runner's hardcoded `-DSIMULATION`, which activates SIMULATION-only debug `$finish`/`$display`/`$stop` (darkriscv.v:897, inside `\`ifdef SIMULATION`→`\`ifdef __PERFMETER__`). Verified the genuine RTL synthesizes cleanly WITHOUT `-DSIMULATION` (214k cells). Drove real in-container yosys synth with the correct ASIC define set + sky130 liberty.
6. **Container path:** project lives outside the iic-eda mount; staged a working copy under `/home/reyerchu/AI_IC_design/2nd__darkriscv_p3` (→ `/foss/designs`) so all EDA paths resolve in-container.
7. **PnR intractable at MLEN=13** (67k-degree nets) → reduced MLEN 13→8 (sanctioned design parameter, documented in config.vh). Re-synth: 11,939 cells, 0.17 mm².
8. **DRT-0305 tie-net** → added `setundef -zero` + `hilomap conb_1`. Resolved.
9. **Detailed-route DRC** → 3 iterations (util 44%→24%→22%→20%, min/max layer, PDN stripe met4): met1 shorts persist ~8.5k regardless → **irreducible within 600 s budget**. Generated GDS from the routed DEF; ran DRC; LVS blocked (no routed netlist).

---

## Honest assessment

- **Phase 1 is genuinely strong** for this CPU: correct class (`processor_cpu`), correct top, full hierarchy, correct 75 MHz clock, faithful datasheet/FRS capture. Only cosmetic defect: `ic_name="SHA256"` stale default label (does not affect the flow).
- **Phase 2's FAIL is an expected model mismatch, not a defect.** The phase2 verification model is hardwired to half-duplex AID peripherals (reset_n/id_bus reference TB + USB-HID tester + DE10 board-pin qsf). A RISC-V CPU has a memory bus, no half-duplex contract, no board-pin SOF — so the reference_tb/qsf/SOF FAILs are categorically inapplicable. The genuine RTL was pulled, license-checked, and proven synthesizable. (Two systematic plugin gaps surfaced: (a) `digital_arithmetic_primitive`/spurious fpu_single match for a CPU, and (b) the runner's blanket `-DSIMULATION` breaks synth of any RTL with SIMULATION-gated `$finish`/`$display` — both worth a backlog entry.)
- **Phase 3 carried genuine silicon backend a long way:** real synth, placement, CTS, **timing closure at 75 MHz**, global route, and a real GDSII — all on the authentic darkriscv RTL via real Yosys/OpenROAD/KLayout. The one genuinely unmet sign-off is **detailed-route DRC convergence**, rooted in darkriscv's behavioral RAM (which upstream itself says should be a hard SRAM macro). This is an honest, documented blocker — not waived without evidence, not faked clean.
- **Tape-out readiness: NO.** A clean route requires either a real SRAM hard-macro for darkram (eliminating the flop-array fanout) or a longer detailed-route budget with congestion-driven placement — beyond this run's scope.
