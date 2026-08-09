# u_hawaii_adc — CLEAN-ROOM FULL run (RESULT)

Run dir: `benchmark-data/ic/u_hawaii_adc/clean_run_v1422_20260715/`
Plugin: vibe-ic **v1.4.22** (cache) · EDA container: **vibeic-eda:0.2.17** (running container `vibeic-eda`, image `vibeic/vibeic-eda:0.2.17`)
Date: 2026-07-15 · Blindness: §4.05 — only the design INPUT docs (`input/docs/L1,L5,L9`) were read; no golden/oracle (`github.com/bmurmann/EE628` GDS/netlist) was consulted.

---

## 1. Headline

**Overall verdict: `FAIL`** (authoritative gate: `flow_compliance_check.py . --flow phase1_phase2_phase3 --strict --skip-hardware`).

The `FAIL` is driven **entirely by the DIGITAL track**, not the analog track. The **ANALOG A1-A9 track converged to its honest, intended state** for a commercial-PDK (IHP SG13G2) mixed-signal IC on the open-source flow:

| Analog step | Verdict | Evidence |
|---|---|---|
| A1 Spec Extraction | **PASS** | real per-block `spec.json` extracted from L5 (both blocks) |
| A2 Topology Selection | **PASS** | real per-block `topology.md` naming device-level primitives |
| A4 Corner Sweep (PVT) | **PASS (real ngspice)** | full 9-corner TT/SS/FF × −40/27/125 °C sweep, `_provenance: real_ngspice`; ldo Vout ≈ 1.199 V across all corners |
| A3 Netlist / A5 Layout / A7 Post-layout resim / A8 Hardmacro / A9 Cosim | **WAIVED-DEFERRED** | `pdk-substitution-v0.2.103` ENV_UNAVAILABLE ticket (SG13G2 has no OSS ngspice/layout/sign-off path) — these five are the `_PDK_SUBSTITUTION_AFFECTED_A_STEPS` |
| A6 Per-block DRC/LVS | **DEFERRED-BY-UPSTREAM(A5)** | A6 is NOT itself pdk-substitution-waivable (deliberately excluded from `_PDK_SUBSTITUTION_AFFECTED_A_STEPS`); it defers because its upstream A5 layout was deferred |
| M1-M4 Mixed-Signal + Step 30 | **DEFERRED-BY-UPSTREAM(A8)** | same waiver chain |

This is **not a faked pass** anywhere: A1/A2/A4 are real artefacts + real ngspice; the layout/sign-off steps are honestly DEFERRED (not counted as executed-PASS) because the target PDK is commercial and unavailable on the OSS path.

Measured: full-flow completion verdict of the canonical Phase-1→Phase-3 runner, plus the A1-A9 analog track. Not a pass@1 dataset score (Shape A single-IC).

---

## 2. Shape

**Shape A — Full runner (chip-grade), canonical Phase-1 entry.**
Entry point: `python3 <cache>/programs/vibe_ic_one_shot_runner.py <project> --pdk sky130A --ic-name u_hawaii_adc --skip-hardware --no-dashboard`.
This is the single product entry (§7.5): Phase 1 (vendor docs L1/L5/L9 → L1-L24) → Phase 2 (digital spec-to-rtl WAIVE) → Analog A1-A9 → Phase 3 (skipped on the phase2 halt). No bespoke benchmark harness.

---

## 3. Score trajectory

| Stage | Action | Result |
|---|---|---|
| Single-shot (runner, blind) | full `vibe_ic_one_shot_runner.py` | phase1 PASS (24/24 L-docs, coverage 100%); phase2 FAIL/halt (data_converter, rtl_gen=null → spec-to-rtl WAIVE); analog dispatched: **A4 PASS_WITH_REAL_SIM** both blocks (auto real-ngspice bypass); A1/A2/A3/A5/A7/A8/A9 WAIVED, A6 FAIL |
| Close-loop A1 | authored real `phase3/analog/<blk>/spec.json` from L5 | A1 PASS (both blocks) |
| Close-loop A2 | authored real `topology.md` (device-level topology) | A2 PASS (both blocks) |
| Close-loop A3 | authored real `<blk>.sp` `.subckt` netlist (device-for-device consistent with the A4 sized decks) | A3 gate PASS standalone; under `--strict` → **WAIVED-DEFERRED** (pdk-substitution, correct) |
| Monte-Carlo | ran `analog_mc_yield_run.py` on both blocks | **unscoreable** (runs_scored=0) — plugin deck-selection gap (see §4-MC) |
| Authoritative gate | `flow_compliance_check --strict` + `phase23_completion_self_audit_check` | **FAIL** — digital spec-to-rtl gap; analog fully WAIVED-DEFERRED/PASS |

Convergence stopped at the honest floor: the analog track cannot advance past A4 on the OSS path (commercial PDK), and the digital track has no synthesizable interface (see §4).

---

## 4. Residual triage (categories A-H per §4)

### 4.1 DIGITAL Step-1 spec-to-rtl FAIL → **Category B (under-specification) / classification gap — FLOOR, blind-unrecoverable without fabrication**

- `ic_class = data_converter` (registry synonym match on "ADC / delta-sigma / converter"). `pure_analog` detector returns `False` ("class 'data_converter' is not analog-only"), so the digital spec-to-rtl step is MANDATORY and its FAIL sets `halted_at=phase2` → overall FAIL.
- **But `u_hawaii_adc`'s actual top interface (L9 `top_ports`, 20 pins) is 100% ANALOG**: `in1..in6` (analog inputs), `vhi/vlo/vldo/vref` (analog refs/supplies), `out1..out6`+`dout` (raw **1-bit modulator bitstream** outputs), `ck4/ck5/ck6` (modulator clocks, direction **output** — on-chip generated). **There is NO digital clock/reset/data-bus input.** L5 explicitly scopes the digital decimation/serial-readout **off-chip** ("generated separately and is out of scope").
- Authoring a synthesizable digital datapath would require **fabricating a clock/reset the pinout does not have** → dishonest. Per §4.2 the AI TRIED and found no honest synthesizable top. **FLOOR-proof:** the given input (L9 interface) is internally self-consistent as an all-analog chip; the digital-RTL expectation comes only from a name-driven class label, not from any interface fact.
- **This is a chip-AGNOSTIC plugin classification gap → GitHub issue filed** (see §7 / captured issues): an ADC whose top interface carries only the raw modulator bitstream (no on-chip digital datapath) should resolve interface-aware to `pure_analog` (which SKIPs RTL) or a data_converter "no-on-chip-digital" sub-path, not be forced down the digital-RTL path.

### 4.2 ANALOG A3/A5/A6/A7/A8/A9 + M1-M4 WAIVED-DEFERRED → **Category D (tool/PDK-substitution) handled by the ENV_UNAVAILABLE waiver — NOT a fresh FAIL**

- L19 declares `pdk_target = sg13g2` (IHP SG13G2, commercial, no public ngspice/layout/sign-off on the OSS path). Every analog SPICE deck (runner's own + the ones authored here) HONESTLY discloses `* pdk_substitution: target=sg13g2 substitute=sky130 …`. The `#438b` PDK-mismatch gate correctly intercepts the substitution and the `pdk-substitution-v0.2.103` waiver downgrades **A3/A5/A7/A8/A9** (the `_PDK_SUBSTITUTION_AFFECTED_A_STEPS` set) to **WAIVED-DEFERRED** (`review_required=True`, not executed-PASS). **A6 is deliberately EXCLUDED** from that set (per-block DRC/LVS is not pdk-substitution-waivable) — here it chains as **DEFERRED-BY-UPSTREAM(A5)** because its upstream A5 layout deferred; M1-M4 + step 30 likewise DEFERRED-BY-UPSTREAM(A8).
- This is the **intended honest behavior** for a commercial-PDK analog IC — the "never fake a pass; let the ENV_UNAVAILABLE machinery do its job" path. A real SG13G2 layout / magic-DRC / netgen-LVS / hardmacro would be sky130 geometry for an SG13G2 target and is correctly deferred for foundry re-characterisation.
- **Underlying capability floor (latent here, would bite a sky130-target analog IC) → GitHub issue [#144](https://github.com/vibeic/vibe-ic/issues/144):** independent of the PDK substitution, the plugin has **no real analog-layout generator** — the `eda_analog_layout` MCP tool's Magic TCL is `readspice` + `gds write` with matching/guard-rings as bare `puts "INFO:"` comments (no placement/paint/PCell/routing), so it streams empty geometry while reporting `DONE: analog layout complete`; and `analog_a5_layout_check` is presence+size-only (a padded stub `.mag` passes — a gate hole). A4's ngspice engine is the only later analog step with a real deterministic generator. A8's Liberty/behavioral-Verilog + A9 numerics are documented as agent-authored judgment (expected), not a program gap.

### 4.3 Monte-Carlo yield unscoreable → **chip-AGNOSTIC plugin bug (does NOT gate the verdict) — GitHub issue filed**

- `analog_mc_yield_run.py` scored **0 runs on BOTH blocks** (`verdict: SKIP`, "MC ran but no run carried a scoreable measure"). Systematic across 2 designs (§4.06).
- Root cause 1 (definitive): `_find_deck()` globs only `phase{2,3}/analog/<block>/*.sp` and returns `sorted(...)[0]` — which is the A3 canonical `<block>.sp`, a bare `.subckt` with **no testbench / `.op` / `.meas`**. The runnable decks (with `.control`/`.meas`/`echo MEAS`) live in `sizing_loop/`, a subdir it never searches. So MC wraps a subckt that nothing instantiates → empty ngspice runs → 0 scored. (This gap pre-exists my A3 authoring: before A3 there was no top-level `.sp`, so `_find_deck` returned None → SKIP either way.)
- Root cause 2 (tool idiom): the wrapper's `.lib sky130.lib.spice mc` errors standalone ("could not find a valid modelname") — the sky130 `mc` section provides only `mc_mm_switch/mc_pr_switch`, not base device models. The correct idiom is `.lib … tt` + the mc switches + an in-`.control` `reset` loop. **Even that hand-rolled idiom did not resample** in this container (30 identical vout, stdev 0.000 mV) — sky130 agauss mismatch was not re-drawn per run. So real MC spread was **not achievable** here; I did NOT fabricate a yield number.
- **Does not gate the verdict**: A4's deterministic PVT corner sweep passed on its own (`analog_a4_corner_sweep_check`); mc_yield is only enforced by the stricter `analog_corner_sweep_check` which is not on this flow's A4 gate.

### 4.4 delta_sigma A4 partial → honest disclosure, not a fail

- delta_sigma corner sweep = `real_ngspice_partial`: 9/9 transient corners ran (SC-integrator settle metric), but `failed_analyses: ['ac']` — the `.ac` open-loop UGBW measurement did not converge in some corners. Disclosed in `corner_results.json`, `spec_results` = `PASS_INFORMATIONAL` (no hard target on the proxy metric). Gate passed on the transient evidence.

No Category A/A2/C/E/F/G/H residuals: the digital gap is B (interface under-provides a digital datapath) + a classification-gap issue; the analog gaps are all D (PDK substitution) governed by the disclosed-substitution waiver.

---

## 5. Tool substitution (mandatory disclosure)

- **Target PDK IHP SG13G2 → sky130A** for all analog SPICE (sizing, PVT corners, MC). SG13G2 has no public ngspice corner library; sky130 LEVEL-1/standin device models are used — **modeled, NOT silicon sign-off**. Disclosed in every deck header (`pdk_substitution:` marker) and honored by the `pdk-substitution-v0.2.103` waiver. Layout / DRC / LVS / hardmacro for the real target are DEFERRED (not run on OSS).
- **ngspice** (vibeic-eda:0.2.17, iic-osic-tools) for analog op/tran/ac — no commercial Spectre/HSPICE.
- **magic 8.3.675 / klayout 0.30.9 / netgen** available in-container but not exercised on the analog blocks (layout track deferred by the PDK-substitution waiver).
- Digital backend tools (yosys / OpenROAD) not exercised — no synthesizable RTL (see §4.1).
- Hardware-in-the-loop (A9) waived: no physical EE628 die on the bench (L9 waives HIL, substitute with cosim — which is itself deferred-by-upstream under the same PDK waiver). `--skip-hardware` passed to the runner.

---

## 6. Reproduce

```bash
# From repo root, with the running vibeic-eda:0.2.17 container named `vibeic-eda`:
CACHE=/home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/1.4.22/programs
PROJ=/home/reyerchu/vibe-ic/benchmark-data/ic/u_hawaii_adc/clean_run_v1422_20260715
# (fresh run dir: only input/docs/{L1,L5,L9}.md copied from the canonical IC input/)
python3 $CACHE/vibe_ic_one_shot_runner.py $PROJ --pdk sky130A --ic-name u_hawaii_adc --skip-hardware --no-dashboard
# analog close-loop: author phase3/analog/<blk>/{spec.json,topology.md,<blk>.sp} then the A-gates fire
# authoritative verdict:
python3 $CACHE/flow_compliance_check.py $PROJ --flow phase1_phase2_phase3 --strict --skip-hardware
python3 $CACHE/phase23_completion_self_audit_check.py $PROJ
```
Input docs: `benchmark-data/ic/u_hawaii_adc/input/docs/{L1_DATASHEET,L5_ANALOG_SPEC,L9_CONSTRAINTS}.md`. Golden oracle (`github.com/bmurmann/EE628`) NOT used.

---

## 7. Sequence / plan status

- This is a single-IC Shape-A run (the analog-track exerciser), not a multi-IC roadmap sweep — no sibling ICs intentionally skipped.
- Phase 3 (digital PnR/DRC/LVS) was legitimately SKIPPED by the runner (halted at phase2; no synthesizable RTL). Not a Shape-E block — it's a downstream consequence of §4.1.
- **Captured chip-AGNOSTIC gaps (GitHub issues on vibeic/vibe-ic; NOT patched in this run):**
  1. **[vibeic/vibe-ic#141](https://github.com/vibeic/vibe-ic/issues/141)** — `data_converter` classification vs all-analog top interface → forces an unauthored digital spec-to-rtl FAIL for an ADC with no on-chip digital datapath.
  2. **[vibeic/vibe-ic#142](https://github.com/vibeic/vibe-ic/issues/142)** — `analog_mc_yield_run._find_deck` picks the bare A3 `.subckt` over the runnable `sizing_loop/` deck → MC scores 0; plus the sky130 `.lib mc` standalone-error + no-per-run-resampling facets.
  3. **[vibeic/vibe-ic#144](https://github.com/vibeic/vibe-ic/issues/144)** — no real analog-layout generator: `eda_analog_layout` streams empty geometry (no placement step) while reporting success, and `analog_a5_layout_check` is presence+size-only (padded-stub gate hole). Latent here (A5 pdk-deferred) but a real floor on an OSS-PDK-target analog IC.
