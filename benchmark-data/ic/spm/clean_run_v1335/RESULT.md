# spm — clean-run spec→GDSII (plugin v1.3.35, 8HD-d / iic-osic-tools)

Clean-room IC benchmark run: blind IC-Expert-Agent authoring from the L1–L9 docs
(no hidden golden read) → full runner Phase 1 → 2 → 3 → sky130A signoff.

## Verdict: silicon signoff PASS (all pillars)
| Pillar | Result |
|---|---|
| Phase 1 (docs→L1–L23) | PASS (auto) |
| RTL authoring (blind) | systolic bit-serial multiplier, iverilog functional 0/64 mismatches |
| yosys synth | PASS |
| PnR (OpenROAD) | PASS (7 spares, density 0.022) |
| GDS streamout (klayout) | PASS — spm.gds 2.6 MB, 0.005µm grid-snapped |
| **DRC** | **0 violations** |
| **LVS** (netgen, power-aware) | **circuits match uniquely** |
| **STA @ 100 MHz (10 ns, sky130_fd_sc_hd)** | **MET — setup +3.82 ns, hold +0.30 ns** |

Completion-audit shows 1 non-signoff FAIL (`project_outputs_in_tree_check` wants
Phase-1 canonical-path artifacts) — an artifact of running phase3 standalone on a copied
subtree, NOT a signoff miss (failed_gates: []).

## Architecture note (the recovery, captured to expert-DB v1.3.35)
First blind attempt used a behavioral form (acc+(y?x:0) per cycle) — functionally correct,
DRC/LVS-clean, but a full 32-bit carry-propagate adder in the path FAILED STA at -24 ns.
Re-authored as the SYSTOLIC carry-save array (1-full-adder critical path) → +3.82 ns MET.
Lesson captured as expert-DB class `serial-parallel-multiplier`.

## Tool substitution
Synopsys VCS→iverilog 12; Design Compiler→yosys; PnR/DRC/LVS/STA→OpenROAD/klayout/netgen
in hpretl/iic-osic-tools (sky130A PDK at /foss/pdks).

## Clean-platform setup requirements surfaced
1. Project must live under the container's bind-mount (`/home/reyerchu/AI_IC_design` →
   /foss/designs); /tmp and other paths are invisible to the sim container → PnR skip-fails.
2. phase3 `--top-name` must match the design top (default chip_top).
3. Flow-ordering: phase2 completion audit gates on `waivers.json`, a phase3 artifact.
