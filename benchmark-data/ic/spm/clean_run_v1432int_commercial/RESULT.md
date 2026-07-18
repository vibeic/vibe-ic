# spm — clean-room A/B re-verify on commercial 180nm PDK (results-only, NDA-excluded)

**Run dir:** `benchmark-data/ic/spm/clean_run_v1432int_commercial`
**Image (A):** `ghcr.io/vibeic/vibeic-eda:0.2.20-int` (id `fa8cb832daf2`) — OpenROAD `1cd84e502a`, yosys `c31dfe3a8` (github.com/vibeic), magic `2431f660`, iverilog `bedf375`.
**Baseline (B):** the `0.2.19` baseline spm run on the same commercial PDK (metrics read numbers-only).
**PDK:** commercial 180nm (staged out-of-repo; read by tools via PATH, never into context). Never silicon-proven.
**Shape:** A (full runner, chip-grade). **Entry:** `vibe_ic_one_shot_runner.py` (Phase-1 → Phase-2 → Phase-3), spec-to-rtl AI-author path (spm is `digital_arithmetic_primitive`, `rtl_gen=null`).

## Headline

- **Overall verdict: FAIL** (phase3 sign-off FAIL — same terminal verdict as the 0.2.19 baseline, different residuals).
- Phase-1 PASS; Phase-2 PASS_WITH_WAIVERS (functional PASS, synth 418 cells, LEC PASS); Phase-3 PnR complete, sign-off residuals below.
- **A/B goal delivered on 1 of 3 focus enhancements:** SOUND post-layout LEC **confirmed improved**; dynamic-IR transient path **present but not wired** (runner gap); LVS **regressed to MISMATCH** in this run.

## ⚠️ A/B confound (must read)

This is a CLEAN-ROOM run: the RTL was **freshly authored** via the runner's `spec-to-rtl` path as a
**shift-add serial/parallel multiplier** (full-width add per cycle). The 0.2.19 baseline used the
canonical **carry-save** spm. The two micro-architectures differ, so **static-IR, STA slack, DRC count,
LVS device count, and LEC point count are confounded by the RTL** and are NOT a pure tool-only A/B.
The most tool-attributable delta is **post-layout LEC soundness** (the LEC recipe itself changed).

## Six-pillar verdict (from completed reports; no close-loop — wind-down)

| Pillar | Verdict | Evidence (numeric) |
|---|---|---|
| 1. Functional coverage | **PASS** | professional cocotb streaming scoreboard PASS; independent golden TB 2006 vectors, 0 mismatch |
| 2. Reference cross-check (LEC) | **PASS** | pre-layout RTL↔netlist equivalent (34 pts, 0 unproven); post-layout netlist↔RTL PROVEN equivalent (243/243) |
| 3. Code coverage ≥90% | not measured | bounded for wind-down |
| 4. FPGA digital | N/A | `digital_arithmetic_primitive` generic track, no board |
| 5. Analog | N/A | pure digital |
| 6. Design-for-ECO | see phase3 sign-off | DRC/LVS residuals below |

## A/B enhancement deltas (0.2.19 baseline → 0.2.20-int)

| Metric | Baseline 0.2.19 | This run 0.2.20-int | Read |
|---|---|---|---|
| **SOUND LEC (post-layout)** | 224 proven / **63 unproven** → UNPROVEN | **243 proven / 0 unproven → equivalent=True** | ✅ **enhancement CONFIRMED** — sound functional-liberty LEC proves every point the baseline left as a black-box floor |
| LEC (pre-layout RTL↔netlist) | equivalent, 129 pts | equivalent, 34 pts | PASS both (point count differs by RTL) |
| **Dynamic IR** | not emitted (static-only) | mode `transient_psm` PRESENT, but **SKIPPED_MISSING_INPUTS** (`--liberty` not wired to the step) | ⚠️ transient PSM path is now in the tool; **phase3 runner does not pass liberty to the dynamic-IR step** → backlog (chip-AGNOSTIC wiring gap) |
| Static IR (worst) | 95.7 mV (5.32% VDD) PASS | 114 mV (6.33% VDD) PASS | both PASS well under 180 mV / 10% budget (confounded by RTL) |
| **LVS** | **MATCH** (netgen+KLayout); NMOS 1590 / PMOS 1589; 0 power-shorts | **MISMATCH**; NMOS 113 / PMOS 880 (lopsided); **0 power-shorts** | ❌ regressed in this run — device recognition lopsided (physically implausible for CMOS) → extraction/comparer residual, not a power short → backlog/triage |
| DRC sign-off | 4533 rules, 15 FAIL | 4533 rules, 56 FAIL | geometry residuals in this run's auto-layout (confounded by RTL) |
| STA (worst setup / hold; aging) | 6.99 / 0.39 ns; aging 7.09 ns PASS | 1.10 / 0.43 ns; aging 2.55 ns PASS | both MET; lower margin = shift-add's longer combinational carry path |

Physical: synth 418 cells; design area 12294 µm²; core-util 44.1%; routed, antenna-clean, fillers placed.

## Residual triage

- **Dynamic-IR SKIP (chip-AGNOSTIC, backlog):** OpenROAD `1cd84e502a` exposes the transient PSM
  (`analyze_power_grid -transient`, vectored L·di/dt) path — `analysis_mode=transient_psm` — but the
  phase3 runner invokes it without the required `--liberty` input → `SKIPPED_MISSING_INPUTS`. Fix routes
  to the phase3 runner's dynamic-IR step wiring (pass the resolved PDK liberty). No droop number could be
  produced this run.
- **LVS MISMATCH (triage/backlog):** KLayout geometric extraction of the GDS vs the gate netlist did not
  cleanly match; device counts NMOS 113 / PMOS 880 are lopsided (extraction did not fully recognise NMOS
  devices); `power_shorts=0`. Likely an extraction/NetlistComparer sensitivity on this smaller shift-add
  layout rather than a real short — needs a focused LVS triage (bulk-normalize / device-extract deck).
- **DRC 56 FAIL:** geometry residuals in the auto-generated shift-add layout (this run's design), vs 15 on
  the baseline's carry-save layout — a design/layout delta, not a demonstrated tool regression.

## Tool substitution (per open-benchmark-methodology §3)

Full OSS forked toolchain `vibeic-eda:0.2.20-int` (no commercial EDA): iverilog (functional), yosys +
OpenROAD (synth/PnR/STA/IR), KLayout SVRF (native in-KLayout DRC on the foundry rule deck) + KLayout /
netgen (LVS), magic. DRC/LVS are native OSS on the commercial rule deck — no commercial-tool cross-run in
this pass.

## Reproduce

```
# fresh container off the integrated image
docker run -d --name <c> -v /home/reyerchu:/home/reyerchu \
  -v /home/reyerchu/AI_IC_design:/foss/designs \
  ghcr.io/vibeic/vibeic-eda:0.2.20-int --skip sleep infinity
# clean-room scaffold: input/docs (spm spec) + input/pdk symlinks → staged commercial PDK
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/vibe_ic_one_shot_runner.py \
  benchmark-data/ic/spm/clean_run_v1432int_commercial \
  --container <c> --pdk auto --top-name spm --ic-name spm --no-dashboard
# spec-to-rtl WAIVE → author phase2/stage1/rtl/spm.v → re-invoke the same command
```
