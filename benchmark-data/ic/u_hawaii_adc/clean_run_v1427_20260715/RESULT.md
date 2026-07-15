# u_hawaii_adc — CLEAN-ROOM FINAL native-PDK-consume run (RESULT)

Run dir: `benchmark-data/ic/u_hawaii_adc/clean_run_v1427_20260715/`
Plugin: vibe-ic **v1.4.27** (repo HEAD f1c121939 — "analog native-PDK 消費") · EDA container: **vibeic-eda:0.2.17** (running container `vibeic-eda`, image `vibeic/vibeic-eda:0.2.17`)
Date: 2026-07-15 · Blindness: §4.05 — only the design INPUT docs (`input/docs/L1,L5,L9`) were read; no golden/oracle (bmurmann/EE628 GDS/netlist) was consulted.

This is THE single blind re-run after the exhausted enhancement batch (v1.4.24–27), measuring the **native custom-PDK consume path** with a **real staged commercial 180 nm NDA PDK** (SPICE model libs + Calibre sign-off decks) — no substitution on the analog track. Purpose: measure the new native-path state honestly, not force a pass.

---

## 1. Headline

**Overall verdict: `FAIL`** (authoritative gate: `flow_compliance_check.py . --flow phase1_phase2_phase3 --strict --skip-hardware`).

The v1.4.27 native-consume path **works end-to-end up to the ngspice model-load boundary** and then hits the honest commercial-PDK floor:

- **Rung-1 native resolution is REAL**: the staged PDK resolves to `source=project_custom_pdk, rung=1`, **no pdk-substitution waiver is synthesized** (contrast the v1.4.22 run, which took the SG13G2 substitution path).
- **A3/A4 device-role resolution is REAL**: `analog_pdk_deck_context` resolves the native nmos (4-terminal) + pmos (5-terminal) device subckts from the staged libs and emits a **native deck carrying the family's own devices** (not sky130 literals).
- **A4 real ngspice sim does NOT converge** on the commercial models → honest **NEEDS_NATIVE_TEMPLATE** (the plugin correctly does **not** fabricate a passing sim). Two layered blockers (issue #149 + the known deeper native-template limitation).
- **#141 is confirmed FIXED at its root** (the all-analog top no longer forces a digital spec-to-rtl FAIL: `rtl_gen` WAIVES "ALL-ANALOG"), and `flow_compliance` routes the digital backend (Steps 34–39, M1–M4) to `N/A`. A **residual** (issue #148) keeps phase2 FAILing: `reference_tb`/`yosys_synth` don't yet honor that N/A.

Measured: full-flow completion verdict of the canonical Phase-1→Phase-3 runner + the A1–A9 analog track on a real commercial PDK. Not a pass@1 dataset score (Shape A, single IC).

---

## 2. Shape

**Shape A — Full runner (chip-grade), canonical Phase-1 entry (§7.5).**
Entry: `python3 <v1.4.27>/programs/vibe_ic_one_shot_runner.py <project> --pdk sky130A --ic-name u_hawaii_adc --skip-hardware --no-dashboard`.
Phase 1 (vendor docs L1/L5/L9 → L1-L24) → Phase 2 (digital; all-analog top → `rtl_gen` WAIVE) → Analog A1–A9 (native-PDK consume — the measurement target) → Phase 3 (skipped on the phase2 halt). No bespoke benchmark harness. v1.4.27 is not cached; run from the repo source at commit f1c121939 (= v1.4.27), which both the worktree and main checkout carry.

---

## 3. Score trajectory

| Stage | Action | Result |
|---|---|---|
| Single-shot (runner, blind) | full `vibe_ic_one_shot_runner.py` | phase1 PASS (24 L-docs); phase2 FAIL (all-analog: `rtl_gen` WAIVE, but `reference_tb`/`yosys_synth` FAIL "rtl/ missing"); analog dispatched, A1–A5 WAIVE / A6 FAIL |
| Staging completeness fix | co-located raw HSPICE libs the converted ngspice wrappers nest-include (they reference bare filenames); staged self-contained OUTSIDE the repo | rung-1 native deck now loads past "file not found" → reaches the real model-closure boundary |
| Close-loop A1/A2/A3 | authored real `spec.json` + `topology.md` (both blocks) + `.sp` netlist (both blocks) from L5 | A1 PASS, A2 PASS, A3 (presence gate) PASS — 2/2 blocks |
| A4 native corner sweep | native deck emitted with resolved device map; real ngspice attempted | **WAIVED — NEEDS_NATIVE_TEMPLATE** (model-closure); honest gap artifact written, no fabricated sim |
| Monte-Carlo | `analog_mc_yield_run.py` on ldo | **no native spread** — MC deck overlays the open-PDK (sky130) mismatch section on the native deck (issue #150); native `mc_libs` not consumed |
| Authoritative gate | `flow_compliance_check --strict` | **FAIL** — 1 FAIL (A3 flow PDK check) + 6 MISSING (A4–A9 blocked-by-upstream) + 51 SKIPPED-CONDITION (digital N/A) + 3 WAIVED-DEFERRED + 2 PASS |

Convergence stopped at the honest native-PDK floor: the analog track cannot really-simulate the commercial models on the OSS ngspice `.lib <section>` path, and the digital track has no synthesizable interface by design.

---

## 4. Native-consume scorecard (the 6 measurement points)

| # | Point | Verdict | Evidence (numbers / error-classes only) |
|---|---|---|---|
| 1 | **#141 all-analog → N/A** | **FIXED-at-root, PARTIAL downstream** | `rtl_gen` → WAIVED ("top interface is ALL-ANALOG; digital RTL steps N/A"); `flow_compliance` routes Steps 34–39 + M1–M4 → `[SKIPPED-CONDITION] N/A for analog IC`. **Residual**: phase2 orchestrator's `reference_tb` (×4 via ECO) + `yosys_synth` still FAIL "rtl/ missing" → phase2 FAIL. Filed **#148**. |
| 2 | **PDK ladder rung-1** | **CONFIRMED** | resolver: `available=True, source=project_custom_pdk, rung=1`; 20 spice libs, 6 mc/mismatch libs, DRC+LVS decks resolved. **No pdk-substitution waiver synthesized** (`native_available_header`, not the substitution marker). |
| 3 | **A3/A4 native device roles** | **RESOLVED (roles) → NEEDS_NATIVE_TEMPLATE (sim)** | `analog_pdk_deck_context`: `status=OK`, device_map = {nmos: 4-term subckt, pmos: 5-term subckt}, `unresolved_roles=[]`. Native deck emitted with the family's device tokens. Real ngspice **did not converge**: (a) primary-lib selection picks the most-sectioned lib, not the device-defining lib → `unknown subckt` (**#149**); (b) even the fully-closed corner section leaves parasitic-diode subckts + per-corner params undefined across sibling sections (deeper native-template limitation, a known follow-on). Honest gap artifact: `phase3/analog/ldo/corner_sweep_native_gap.json`. |
| 4 | **MC yield** | **NO native spread (honest gap)** | MC deck overlays open-PDK `sky130.lib.spice tt_mm` on the native deck + native devices → `PDK_MISMATCH` on every `mc_runs/*.sp`, and the sky130 mismatch statistics do not apply to native devices (degeneracy). Native `mc_libs` not consumed by the MC path. Filed **#150**. Degeneracy guard did not need to fire — the deck is PDK-mismatched before spread is measured. |
| 5 | **A5 auto-layout** | **HONEST GAP (WAIVE)** | no in-image ALIGN/auto-layout → no `layout.mag` / block GDS → A5 WAIVED. Known follow-on (#144, closed) — referenced, not re-filed. |
| 6 | **A6 native PV** | **HONEST DEFERRAL (FAIL, no stub)** | A6 requires a block GDS (from A5) + DRC/LVS decks. Decks resolved; **block GDS absent** → native per-block PV cannot run → A6 **FAIL** (`A6_PV_DRC_NO_EVIDENCE`). The geometry gate holds: **no deterministic stub falsely passes**. Deferral is honest (blocked-by-upstream A5). |

**Final `flow_compliance --strict` verdict: `FAIL`.** Per-step summary: 2 PASS, 3 WAIVED-DEFERRED, 51 SKIPPED-CONDITION (digital N/A on the all-analog top), 6 MISSING (A4–A9, blocked-by-upstream A3), 1 FAIL (A3 flow PDK check — see #151). Full analog A-step table below.

### Analog A1–A9 per-step (both blocks, final converged)

| Step | ldo | delta_sigma | note |
|---|---|---|---|
| A1 Spec Extraction | PASS | PASS | real per-block `spec.json` from L5 |
| A2 Topology Selection | PASS | PASS | real device-level `topology.md` |
| A3 Netlist Gen (presence gate) | PASS | PASS | `.subckt` present, 2/2 clean |
| A3 Netlist PDK check (flow gate) | FAIL | FAIL | native custom-PDK include not recognized + MC sky130 decks → `PDK_MISMATCH`/`NO_MODEL_INCLUDE` (**#151**) |
| A4 Corner Sweep (PVT) | WAIVED (NEEDS_NATIVE_TEMPLATE) | WAIVED (no DC template) | native deck emitted; ngspice model-closure floor |
| A5 Layout | WAIVED | WAIVED | no auto-layout (#144) |
| A6 Per-block PV | FAIL (no GDS, no stub) | FAIL (no GDS, no stub) | honest deferral, geometry gate holds |
| A7 Post-layout resim | WAIVED | WAIVED | blocked-by-upstream A5 |
| A8 Hardmacro | WAIVED | WAIVED | blocked-by-upstream A5 |
| A9 HW verify | WAIVED | WAIVED | `--skip-hardware` + upstream |

---

## 5. Residual triage (categories A–H per §4)

- **A4 native sim non-convergence → Category C (tool-gap) / FLOOR.** The converted commercial ngspice model libs are not self-contained under ngspice's `.lib <path> <section>` mechanism: device macros reference parasitic-diode subckts + per-corner params (noise / well-diode / metal-RC) spread across many sibling sections that no single section closes (observed on the device-wrapper lib, the master-corner `ttt`, and the shim `ttt_lv_full`). This is the commercial-PDK OSS-ngspice floor for this NDA node — a native device+corner template / model-closure work-item, not a chip-agnostic emitter defect. **Correctly not faked** (A4 WAIVED, no `simulator_run=true` stub).
- **Primary-lib selection → Category real (chip-agnostic bug), filed #149.** Independently fixable; it manifests first (`unknown subckt`) even before the model-closure floor.
- **MC open-PDK overlay → Category real (chip-agnostic bug), filed #150.**
- **A3 flow PDK check custom-PDK blindness → Category real (chip-agnostic bug), filed #151.**
- **#141 downstream N/A residual → Category real (chip-agnostic bug), filed #148.**
- **A5/A6 → Category C (tool-gap) / FLOOR**, ALIGN image integration (#144, known) — referenced.

The digital-track FAIL is Category B/floor and unchanged in nature from the prior run: the top interface (L9, 20 pins) is 100% analog (raw modulator bitstream out; no digital clock/reset/data input); authoring a synthesizable datapath would fabricate a clock the pinout lacks.

---

## 6. Tool-substitution disclosure (mandatory)

- **Analog track: NO substitution — ran on the REAL target PDK.** The A1–A9 analog track consumed a **real staged commercial 180 nm NDA PDK** (SPICE model libraries + Calibre DRC/LVS sign-off decks) via the rung-1 `project_custom_pdk` native path. `analog_real_corner_sweep` emitted the native deck against the staged libs (device tokens = the family's own subckts). The corner sweep therefore attempted **real ngspice on the commercial models** — its non-convergence is a real property of the model bridge, not a substituted-PDK artifact.
- **Digital / phase3 remains sky130A** (the `--pdk sky130A` default), but phase3 is SKIPPED here (all-analog top, phase2 halt) so no digital GDS was produced. Standard OSS substitutions (Synopsys VCS→iverilog, DC→yosys+OpenROAD, Calibre→native svrfdrc/KLayout) apply where a digital backend runs.
- **NDA hygiene**: all PDK content and any ngspice sim scratch that embeds native model-lib paths or quotes native model text is staged out-of-repo and git-excluded (`.gitignore`: `input/pdk/`, `phase3/analog/*/sizing_loop/`). This RESULT and all committed artifacts carry **numbers + error-classes only** — no PDK content, no foundry/SKU literal.

---

## 7. Captured issues / follow-ons

**Filed this run (NEW chip-agnostic gaps, evidence-backed, no plugin patching):**
- **#148** — phase2 orchestrator: all-analog N/A not honored by `reference_tb`/`eco_loop`/`yosys_synth` (residual of #141) → phase2 FAILs on "rtl/ missing".
- **#149** — `analog_pdk_deck_context`: primary corner-lib selection ("most sections") ignores resolved `device_map` membership → ngspice "unknown subckt" on a multi-lib custom PDK.
- **#150** — `analog_mc_yield_run`: MC deck overlays open-PDK (sky130) mismatch section on a rung-1 native custom PDK (doesn't consume resolved `mc_libs`) → `PDK_MISMATCH` + no native spread.
- **#151** — `analog_netlist_pdk_check`: no recognition of a rung-1 native custom-PDK model include (sky130/gf180-only) → A3 flow-gate can't pass on an all-native custom PDK.

**Known follow-ons (referenced, NOT re-filed):** deeper native device+corner templates / model-closure (the A4 floor); rung-2 container-lib discovery; ALIGN auto-layout image integration (#144, A5/A6).

**#141** (data_converter forces digital spec-to-rtl FAIL) — verified **fixed at root** (CLOSED); the downstream residual is tracked separately in #148.
