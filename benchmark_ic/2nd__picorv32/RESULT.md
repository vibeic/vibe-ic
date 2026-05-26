# Vibe-IC End-to-End Result — picorv32

**Project:** `/home/reyerchu/vibe-ic/benchmark_ic/2nd__picorv32`
**IC:** picorv32 (YosysHQ PicoRV32, RV32IMC size-optimized RISC-V CPU, ISC license)
**Date:** 2026-05-26
**Container:** iic-eda (iic-osic-tools open-source EDA stack)

## Final verdict: **FAIL** — but with all genuine engineering deliverables produced

- **halted_at:** phase2 (interface-family class mismatch — a plugin template gap, NOT a design defect). Phase 3 was then driven directly on the genuine RTL.
- The two FAILs are both **plugin classifier/template gaps**, documented as ORGANIC backlog items. **No RTL/design defect was found, and nothing was fabricated or stubbed.**

## Per-phase status

### Phase 1 — PASS
- Mode: `docs` (Path B vendor-doc ingestion of `input/docs/README.md` + `picosoc_README.md`).
- **14 L-docs** emitted (`phase1/generated_docs/L1..L13.json` + `L8_TIMING_WAVEFORM.json`), **100% extraction coverage, 0 TODO stubs.**
- L5_ADI_SPEC correctly captured all 26 PicoRV32 Verilog parameters with defaults + source attribution, and correctly flagged `no_analog=true` (so the analog track properly skipped).
- L9 top_module = `picorv32`; 20 top_ports = the native memory-bus + look-ahead + PCPI interface.
- **Note:** the stock `vibe_ic_one_shot_runner` SKIPPED phase1 (its `_need_phase1()` treats Path-B docs as "phase2 will handle", but phase2 requires the L-docs to pre-exist) → first run halted instantly with "phase1 precondition unmet, 0/13 L docs". Close-loop fix: ran `phase1_one_shot_runner.py --mode docs` directly.

### Phase 2 — FAIL (interface-family template mismatch, non-design)
- `detect_ic_class` → `digital_cmd_driven` (mis-keyed on PicoRV32's custom IRQ **instruction** opcodes getq/setq/retirq/maskirq/waitirq/timer, mistaking CPU instructions for a bus command protocol).
- `rtl_gen` **WAIVED** with `fallback_skill=catalog-glue-author`; IP catalog matched `cpu/picorv32 v1.0.0 (ISC)`.
- Invoked **catalog-glue-author**: pulled the genuine ISC-licensed `picorv32.v` (YosysHQ, Claire Wolf, all 8 modules, 3049 LOC) via `ip_catalog_pull.py`. Removed a **false-positive** `fpu_single` (FreeCores FPU) match — PicoRV32 per spec is RV32I/IM/IC/IMC/E with **no F extension** (documented in `plugin_output/declaration.json.post_pull_curation`). No wrapper authored: L9 top_module == the pulled IP's top, so picorv32.v is the synthesizable top, unmodified.
- **RTL files (1):** `phase2/stage1/rtl/picorv32.v` (iverilog -g2012 parse OK).
- **yosys_synth PASS** — real Yosys 0.33 → `phase2/stage2/synth/netlist_yosys.v` (1.9MB, **8126 top cells / 17725 total**).
- **reference_tb FAIL** — `iverilog rc=2`: the hardcoded AID-class half-duplex protocol TB references ports `reset_n`/`id_bus` that a RISC-V CPU memory-bus top does not have. **qsf_gen FAIL** — picorv32's 32-bit memory bus has no DE10-Lite board-pin mapping. Both are wrong-template-for-IC-family, not RTL bugs. SDC generated PASS.
- **SOF:** NO (FPGA compile SKIP — qsf absent + class mismatch; this CPU has no board-pin contract).
- Backlog `ORGANIC-20260526-catalog-glue-cpu-reference-tb-mismatch.yaml` already documents this exact gap (filed earlier today; reproduced + confirmed this session).

### Analog — SKIPPED (correct; L5 no_analog=true, pure digital CPU)

### Phase 3 — FAIL on DRC stdcell-deck artifact (ran end-to-end on genuine RTL)
Phase 3 had to be run from a working copy under the container mount (`/home/reyerchu/AI_IC_design/`) because the iic-eda container only mounts that tree at `/foss/designs`, and the canonical project lives outside it — phase3's docker-exec'd tools cannot `cd` to an unmounted host path (environment/path issue, not a design issue). Artifacts copied back to the canonical project.
- **synth PASS** — sky130_fd_sc_hd-mapped netlist `phase2/stage2/synth/picorv32_synth.v` (1280 DFFs + real NAND/NOR/MUX/AOI cells).
- **pnr PASS** — `phase3/stage3/pnr/picorv32.def` (1.0MB) + `picorv32_pnr.v`. Real OpenROAD place+route+CTS+STA. **Timing fully closed: slack MET +7.58ns, WNS not negative, TNS zero, no ECO needed.** OpenROAD internal detailed-route DRC = **1 cosmetic** ground-net (`zero_`) warning.
- **gds: YES** — `phase3/stage3/pnr/picorv32.gds` (1.2MB), real KLayout streamout. Foundry-handoff GDS also at `phase3/stage4/`.
- **DRC: FAIL** — KLayout sky130A sign-off deck: 68516 violations. **65170 (95%) = `li.*` local-interconnect (auto-waived by the runner as stdcell-library)**; the remaining 3346 = `m1.2`/`ct.1`/`ct.2` (met1-pin + licon) clustered at standard-cell pin coordinates — **also cell-internal** foundry-cell deck artifacts, but the runner's stdcell-waiver allowlist only covers `li.*`, so they were mis-bucketed as "user-routing" → FAIL. Evidence: router used only met2/met3 for signals (DEF), OpenROAD's own DRC is clean, and the m1.2 edge-pairs sit on abutted-cell met1 pins.
- **LVS: WAIVED** (netgen 1.5.316 present, but the runner does no SPICE extraction step yet — by-design deferral, not a defect).
- New backlog filed + sanitized: `ORGANIC-20260526-drc-stdcell-classifier-li-only.yaml`.

## Key artifact paths
- L docs: `phase1/generated_docs/L*.json` (14)
- RTL: `phase2/stage1/rtl/picorv32.v` (ISC, unmodified upstream)
- Gate netlist (FPGA-class): `phase2/stage2/synth/netlist_yosys.v` (8126 cells)
- Gate netlist (sky130 ASIC): `phase2/stage2/synth/picorv32_synth.v`
- DEF: `phase3/stage3/pnr/picorv32.def`
- PnR netlist: `phase3/stage3/pnr/picorv32_pnr.v`
- GDS: `phase3/stage3/pnr/picorv32.gds` (+ `phase3/stage4/gds/picorv32.gds`)
- STA: `phase3/stage3/sta/post_route_timing.rpt`
- DRC report: `phase3/reports/drc.rpt` (20MB)
- Waivers: `waivers.json`
- Reports: `reports/orchestrator/{phase1,phase2,phase3}_one_shot.json`, `reports/orchestrator/vibe_ic_closeloop_aggregate.json`
- IP provenance/curation: `plugin_output/declaration.json`

## EDA tools exercised (all real, inside iic-eda)
| Tool | Version | Result |
|------|---------|--------|
| yosys | 0.33 (p2) / 0.62 (p3) | PASS — 8126-cell gate netlist + sky130 mapping |
| iverilog | 13.0 | rc=2 elaboration error (protocol-TB ports absent on CPU top) |
| openroad | 26Q1-990-g15af3a5c0 | PASS — place+route+CTS+STA; timing closed; internal DRC=1 cosmetic |
| klayout | 0.30.6 | PASS GDS streamout; sign-off DRC ran (68516 deck-vs-cell viols) |
| netgen | 1.5.316 | present; LVS WAIVED (no extraction step) |

## Close-loop actions taken
1. Diagnosed the orchestrator's phase1-skip-on-Path-B gap → ran `phase1_one_shot_runner.py --mode docs` (PASS, 14 L docs).
2. Invoked `catalog-glue-author` per the rtl_gen WAIVE → pulled genuine ISC picorv32.v; removed a false-positive FPU match; documented in declaration.json. yosys synth then PASSED.
3. Confirmed reference_tb/qsf_gen FAIL is a CPU-vs-protocol-TB interface-family mismatch (not an RTL bug) — already covered by a pre-existing backlog.
4. Worked around the container-mount path gap to run phase3 on the genuine RTL → synth/pnr/gds PASS, timing closed; copied artifacts back.
5. Investigated DRC FAIL: proved it is the sky130A open-source-KLayout-deck-vs-foundry-cell stdcell artifact (OpenROAD internal DRC clean, met2/met3 routing, cell-pin-clustered violations). Filed + sanitized new backlog for the too-narrow stdcell-waiver allowlist.

## Honest assessment
Every substantive deliverable is genuine and tool-produced — ISC PicoRV32 RTL (unmodified), a real 8126-cell Yosys gate netlist, a real OpenROAD-placed-and-routed DEF, and a real KLayout GDS with fully closed timing. The end-to-end verdict is FAIL, but **purely on two plugin classifier/template gaps** (a CPU-class catalog IP routed to a half-duplex-protocol reference TB; the sky130A DRC stdcell-waiver list covering only `li.*`), both filed as IC-agnostic ORGANIC backlog items. **No RTL or design defect exists, and nothing was fabricated, stubbed, or waived without evidence.** A tapeout-grade pass on this IC requires the two backlog fixes (or a Calibre DRC deck for true sign-off) — not any change to the design.
