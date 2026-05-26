# benchmark_ic — fresh re-run tracker

Fresh re-run of the **vibe-ic plugin + MCP-EDA** full flow (Phase 1 → 2 → 3) on
all ICs from the **2nd benchmark (8)** and **4th benchmark (13)** = **21 ICs**.

- Each project seeded from its source IC's `input/` only (Path B vendor docs).
- Runner: `vibe-ic-marketplace/plugins/vibe-ic/programs/vibe_ic_one_shot_runner.py <proj> --container iic-eda`
- Container: `iic-eda` (hpretl/iic-osic-tools) — yosys/openroad/klayout/netgen/magic/iverilog/ngspice all present.
- Driven by fresh sub-agents, dispatched in batches of ~5.

## Known caveat
- `2nd__VexRiscv` & `4th__VexRiscv` ship only SpinalHDL Scala (no checked-in Verilog).
  RTL-gen needs `sbt`+JVM — **NOT installed**. Expected to halt at RTL-gen unless toolchain added.

## Status legend
PENDING · RUNNING · PASS · PASS_WITH_WAIVERS · FAIL · BLOCKED

| # | Project | Source | Batch | Status | Halted at | Notes |
|--:|---------|--------|:-----:|--------|-----------|-------|
| 1 | 2nd__cv32e40p | 2nd/cv32e40p | 2 | FAIL | phase3 | routed GDS(23484 cells) NOT signed off; STA WNS -21.68ns; KLayout DRC 138804 REAL; Magic=vacuous(confirmed); route !converge; FIXED catastrophic regex-hang in phase1 |
| 2 | 2nd__darkriscv | 2nd/darkriscv | 2 | FAIL | phase3 | HONEST: synth 11939 cells,timing CLOSED@75MHz,GDSII; detailed-route DRC did NOT converge(~16-18k met1 shorts/behavioral RAM); LVS blocked |
| 3 | 2nd__ibex | 2nd/ibex | 3 | PASS_WITH_WAIVERS | phase3 | phase3 FULLY CLEAN: GDS 1.88MB,14862 cells; Magic DRC=0; LVS exact 14862=14862; STA clean@33ns; only CPU-class p2 gates waived |
| 4 | 2nd__neorv32 | 2nd/neorv32 | 3 | FAIL | phase3 | netlist(574831 cells/213k DFF,8.3mm2)+placed DEF; NO routed GDS(213k-fanout clk,memories→flops,no SRAM macro); fixed yosys proc_dlatch segfault; GDS vacuous(confirmed) |
| 5 | 2nd__picorv32 | 2nd/picorv32 | 1 | FAIL | phase2 | genuine GDS+timing-closed; 2 plugin-classifier gaps filed (not design defects) |
| 6 | 2nd__serv | 2nd/serv | 1 | FAIL | phase2 | real SOF (Quartus, timing clean); fixed 2 plugin checker bugs; CPU mem-bus !=half-duplex TB model |
| 7 | 2nd__U_Hawaii_DeltaSigma_ADC | 2nd/U_Hawaii | 4 | FAIL | A5/phase3 | analog A1/A3/A4/A7 PASS both blocks(real ngspice,LEF/Lib/GDS); pulled real EE628 upstream; DRC 1066(IHP),LVS mismatch-honest; no digital RTL→phase3 N/A |
| 8 | 2nd__VexRiscv | 2nd/VexRiscv | 5 | FAIL | phase3 | UNBLOCKED→routed GDS 1.22MB(6964 cells,15859 gates); STA WNS -29.08ns,no hold viol; KLayout DRC 56415 REAL(geom verified); Magic-trap avoided; LVS waived-honest |
| 9 | 4th__cv32e40p | 4th/cv32e40p_e2e | 2 | FAIL | phase3 | reached GDS 2.56MB(19893 synth/23331 PnR); hold clean,WNS -21.32ns(simclkgate); DRC false-pos(no signoff); LVS dev 23331==; fixed STA-0164 dlatch bug |
| 10 | 4th__darkriscv | 4th/darkriscv_e2e | 3 | FAIL | phase2 | reached GDS(4800 cells,993KB); DRC=0 Magic-clean; LVS 5053=5053; STA WNS -1.52ns@50MHz; found -DSIMULATION synth-poison gap |
| 11 | 4th__ibex | 4th/ibex_e2e | 3 | FAIL | phase3 | GDS 1.89MB(14293/14798 cells); WNS -4.13ns; *Magic=0 is VACUOUS* (LEF-abstract GDS unreadable); real DRC 126k/KLayout 87.8k; LVS pin-fail; NO real signoff |
| 12 | 4th__neorv32 | 4th/neorv32_e2e | 4 | FAIL | phase3 | reached GDS(48230 cells,1.587mm2,largest); router DRC=1; LVS dev-count PASS; STA closes @200ns(+40.23ns); KLayout711k/Magic2.24M handoff-artifact(honest) |
| 13 | 4th__picorv32 | 4th/picorv32_e2e | 1 | PASS_WITH_WAIVERS | phase3 | full flow→GDS; DRC clean(Magic re-stream); LVS MISMATCH(wrapper o/p shorts, honest); fixed 4 phase1 bugs |
| 14 | 4th__serv | 4th/serv_e2e | 1 | FAIL | phase2 | drove phase3→routed GDS(8853 inst); DRC FAIL(~124k KLayout handoff); LVS waived; P0 backlog nonprotocol-verif-path |
| 15 | 4th__sha256_rerun | 4th/sha256_rerun_e2e | 1 | BLOCKED | phase2 | 14 L docs+real netlist+SOF+passing sim; phase2 protocol/analog gates reject pure-digital primitive; backlog filed (local) |
| 16 | 4th__sha256_v2 | 4th/sha256_v2_e2e | 2 | FAIL | phase2 | reached phase3 GDS(8.3MB,11380 cells)+real SOF; DRC 73086/73167 li-layer false-pos; LVS waived; class-mismatch gates only |
| 17 | 4th__sha256_v2variant | 4th/sha256_v2variant_e2e | 2 | FAIL | phase2 | reached GDS(8.3MB,9959 cells,0 TritonRoute viol)+SOF; DRC 83193/83866 stdcell false-pos; found --util fraction gap |
| 18 | 4th__spm | 4th/spm_e2e | 1 | BLOCKED | phase2 | phase1 PASS+real RTL(5008-vec golden TB)+yosys 304 cells; AID protocol-TB can't elaborate clk/rst/x/y/p; backlog 3rd repro |
| 19 | 4th__subservient | 4th/subservient_e2e | 3 | FAIL | phase2 | reached phase3 GDS(901 cells,STA +13.15ns); DRC 6777/6957 false-pos(Magic-confirmed); LVS waived; orch FAIL@p2 |
| 20 | 4th__U_Hawaii_DeltaSigma_ADC | 4th/U_Hawaii_e2e | 4 | PASS_WITH_WAIVERS | none | analog A1-A7 PASS both blocks(real ngspice/KLayout/netgen); phase3 GDS DRC CLEAN+LVS MATCH on real upstream chip(171 cells,2624 dev); A8 hw waived(cosim); flow_compliance PASS=5/0; 32 doc waivers |
| 21 | 4th__VexRiscv | 4th/VexRiscv_e2e | 5 | FAIL | phase3 | UNBLOCKED→routed GDS 1.2MB(6964 cells); STA WNS -29.08ns; KLayout DRC 56415 REAL; Magic vacuous(467 unknown-layer,rejected); LVS not signed off; honest |

_Updated by the orchestrator as agents report back._

## CRITICAL signoff caveat (from 4th__ibex finalizer, 2026-05-26)
The benchmark phase3 streams GDS from **LEF abstracts** (`stream_out.py`), so cell-internal/
routing geometry lands on layers Magic's `gds read` cannot interpret. Magic then reads an
(near-)empty layout and reports **0 DRC violations — which is VACUOUS, not clean**. Sibling
runs that reported "Magic DRC = 0 / clean" (2nd__ibex, 4th__darkriscv, 4th__subservient) are
suspect for the same reason. Honest full-geometry checks show 80k-126k violations dominated by
intra-stdcell / well-tap artifacts. **No digital benchmark here achieved genuine DRC/LVS sign-off**;
they reach a routed GDS only. Real sign-off needs Magic-native def-read→gds-write (on-grid) or a
Calibre deck. Treat all "DRC clean" claims below as "routed-GDS reached", not "signed off".

