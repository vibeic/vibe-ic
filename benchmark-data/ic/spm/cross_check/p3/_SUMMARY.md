# Phase-3 Cross-Check Summary — OURS (carry-save spm) vs REF (shift-add spm)

Methodology: OURS is a deliberately DIFFERENT micro-architecture (carry-save) than
the REF (shift-add), so layout/netlist are NOT expected to be identical. Valid
cross-check = (a) metrics in a sensible range vs REF, and (b) both independently
pass sign-off. All tool runs done in the iic-eda container on real artifacts.

| Step | Item | Verdict | OUR vs REF (key metric) |
|---|---|---|---|
| 15 | Floorplan / PDN | MATCH / IN-RANGE | die 200x200 µm both; util 6.6% vs 9.2% |
| 16 | Clock planning | MATCH | single clk, clkbuf-chain heuristic (both) |
| 17 | Placement | BOTH-CLEAN / IN-RANGE | check_placement clean both; 2029 vs 2883 µm² |
| 18 | Spare-cell + ECO-prep (Design-for-ECO) | BETTER-THAN-REF | OURS 7 spares (inv/nand2/nor2/mux2/aoi/dff) @ d=0.0232, distributed+tied-off, coverage PASS + preservation removed:0 keep-intact; REF has **0 spares / 0 dont_touch** |
| 19 | CTS | IN-RANGE / BOTH-CLEAN | 5 buf/33 sink vs 9 buf/64 sink; depth 2 both |
| 20 | Post-CTS hold | BOTH-CLEAN | "No hold violations" both; FF hold +0.30 ns both |
| 21 | Routing | BOTH-CLEAN / IN-RANGE | DRT=0 both; 281 vs 330 nets; top met3 both |
| 22 | SPEF (GAP-CLOSE) | IN-RANGE | R 16.1k vs 21.2kΩ; C 0.471 vs 0.604 pF |
| 23 | Post-route STA | BOTH-CLEAN | SS +6.61/TT +12.41/FF +14.59 ns; REF SS +16.87, all MET |
| 24 | IR drop (GAP-CLOSE) | BOTH-CLEAN | worst 128 µV vs 44 µV (both <0.01% Vdd) |
| 25 | EM (GAP-CLOSE) | BOTH-CLEAN | 34.5% vs 10.7% of J_max (both PASS) |
| 26 | Antenna (GAP-CLOSE) | BOTH-CLEAN | 0/0 net/pin viol both |
| 27 | Signal integrity | BOTH-CLEAN / no-dedicated-tool | OUR coupling <0.1 fF (all sub-threshold) vs REF 21.3 fF max |
| 28 | Post-layout gate sim + SDF | PASS (exceeds REF) | OUR gate sim PASS 10013 vec; REF flag-only |
| 29 | Post-layout SPICE | PASS (exceeds REF) | OUR tpd 131.8/128.4 ps; REF measure FAILED. Full-chip = NO-TOOL both |
| 30 | PV (DRC+LVS+ERC) | BOTH-CLEAN | DRC li-class only (0 met2+) both; LVS 3176/3176 device-exact both |
| 32 | Power (GAP-CLOSE refine) | IN-RANGE | 1.79e-4 W (SPEF) vs 1.57e-4 W |
| 33 | Metal fill | IN-RANGE / no-fill-tool | li1 2.50%/met1 1.53% vs 3.48%/2.20%; density_fill broken both |
| 34 | Tapeout checklist | BOTH-CLEAN / PASS_WITH_WAIVERS | full signoff matrix both; same waivers |
| 35 | GDSII | BOTH-CLEAN + FUNC-EQUIV | clean+func-equiv (NOT pixel); 375 vs 285 KB |
| 36 | Foundry handoff | BOTH-CLEAN / IN-RANGE | same kit shape; mask/WAT TODO-templated both |

## NEW step in the 56-step flow
- **Design-for-ECO (Step 18)**: a distributed, tied-off pool of 7 spare std cells
  (inv/nand2/nor2/mux2/aoi/dff) was inserted as FIXED `dont_touch`/`keep`
  instances after placement / before CTS. Coverage PASS (d=0.0232 ≥ 0.02,
  7 distinct positions) + preservation intact (removed 0, keep-attr intact).
  REF (`spm_e2e`) has **0 spares / 0 dont_touch** → OURS is BETTER-THAN-REF
  (adds metal-only-ECO readiness the reference lacks). See `step_18.md`.

## Gaps CLOSED in this cross-check (with real tool runs on OURS)
- **SPEF (22)**: OpenRCX `extract_parasitics` on routed.def → `spm_xc.spef` (279 nets, R 16.1kΩ, C 0.471pF).
- **IR drop (24)**: pdngen PDN + PDNSim `analyze_power_grid` → worst 128 µV (<0.01% Vdd).
- **EM (25)**: `analyze_power_grid -enable_em` → worst 34.5% of met1 J_max.
- **Antenna (26)**: `check_antennas` → 0 net / 0 pin violations.
- **SI (27)**: SPEF coupling extraction → all Cc <0.1 fF (lower exposure than REF).
- **Post-layout gate sim (28)**: real iverilog gate sim of routed netlist vs 10013 golden vectors → PASS.
- **Post-layout SPICE (29)**: ngspice critical-path cell (xor2_1) → tpd ~130 ps (REF's own measure failed).
- **Power (32)**: SPEF-annotated `report_power` → 1.79e-4 W (resolves clock power).
- **Multi-corner STA (23)**: SS/TT/FF re-derived with SPEF back-annotation, all MET.

## Genuine NO-TOOL / partial
- **Full-chip SPICE (29)**: no open-source fast-SPICE for whole netlist — NO-TOOL (same as REF; REF also only did a single-cell SPICE, and its measure failed).
- **SDF *timing* annotation in gate sim (28)**: iverilog `-gspecify` errors on sky130 power-pin specify blocks of unused cells — same open-source limitation the REF flow acknowledges. SDF file is valid (633 IOPATHs); logical gate-sim PASSES.
- **Automated metal fill insertion (33)**: OpenROAD `density_fill` JSON-schema broken in the 26Q1 build — documented by REF too. Density was measured on both.

## Highlights (OUR vs REF)
OURS is consistently leaner (carry-save: 249 vs 302 cells, 281 vs 330 nets, util
7.5% vs 10.5%) with proportionally smaller parasitics/CTS/routing — all IN-RANGE.
Both independently pass every sign-off: DRT=0, antenna 0/0, DRC li-waivable only
(0 met2+), LVS device-exact 3176/3176, all STA corners MET, IR/EM/SI within budget.
OURS' setup margin is tighter at SS (+6.61 vs +16.87 ns) due to the longer
carry-save combinational chain, but stays > 6 ns positive on a 20 ns clock. On
post-layout sim and critical-path SPICE, OURS produced real passing results where
the REF used flag-approximations or hit a measure bug.
