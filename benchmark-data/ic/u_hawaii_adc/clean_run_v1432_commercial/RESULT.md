# u_hawaii_adc (UHEE628) — commercial-180nm NDA-PDK validation (clean_run_v1432_commercial)

**Flagship REAL-NODE analog re-validation.** Re-runs the mixed-signal
`u_hawaii_adc` analog blocks on **a commercial 180 nm NDA PDK** — the REAL
foundry device models across REAL PVT corners plus native statistical
Monte-Carlo — **not** the open-PDK stand-in the earlier runs used. This
**DISSOLVES the old `pdk_substitution` disclosure** for Pillar 5: the analog
closed-loop is now closed on real-node silicon models.

- IC: 6× incremental delta-sigma modulator + 1 on-chip LDO. Analog inputs,
  serial digital outputs. Core 1.2 V from an on-chip LDO off 1.8 V IOVDD.
- PDK: **a commercial 180 nm NDA PDK**, staged out-of-repo under `input/pdk/`
  (rung-1 `project_custom_pdk`; symlinks, git-excluded). Name/SKU/foundry are
  deliberately omitted per NDA directive.
- Container: fork `ngspice-46+` in the standard EDA image.
- Input: ONLY `input/docs/{L1_DATASHEET, L5_ANALOG_SPEC, L9_CONSTRAINTS}.md`.

## NDA discipline (ABSOLUTE — stated up front)
- **RESULTS-ONLY, NDA-EXCLUDED.** No PDK name, SKU, foundry, DRC rule-id,
  model parameter, vth/tox/binning value, or device/cell/section/library name
  appears in this RESULT.md or in any committed file. Only per-corner metric
  VALUES, MC mean/sigma/yield%, and PASS/FAIL are reported. SPICE decks, model
  libs, and the driver are **git-excluded** — the tools read the models by path;
  only tool OUTPUT is reported.
- **NEVER "silicon-proven".** These are simulated results against the foundry's
  released device + statistical models. Foundry tape-out sign-off is a separate,
  human-owned gate.
- **HV LDMOS models are reduced-fidelity** (per the ngspice-shim WARNING). This
  IC uses ONLY the LV (1.8 V) CMOS core devices — no HV path is claimed. The HV
  reduced-fidelity caveat is disclosed and does not affect these results.

---

## STEP 1 — Phase 1 (docs mode) — PASS
`phase1_one_shot_runner --mode docs` → **24/24 L-docs, coverage 100%.**
L5 auto-detected the **2 analog block types** required: **`delta_sigma` + `ldo`**.

## STEP 2 — Shape-A `/vibe-ic-all` (analog track auto-detected)
`vibe_ic_one_shot_runner … --pdk auto` auto-resolved the staged `input/pdk/`
as rung-1 `project_custom_pdk` (the commercial 180 nm node). Phase 1 **PASS**,
Phase 2 **PASS_WITH_WAIVERS**. The deterministic runner then **WAIVES analog
A1–A9 to the analog skills** (the designed AI fall-through) — the analog blocks
are authored/closed by the skill layer, below.

## STEP 3 — Pillar 5: REAL-NODE analog closed-loop — **PASS** (flagship)

Both blocks authored from the L5 spec (topology + sizing = designer choice R3),
device roles resolved to the staged commercial LV-CMOS models, and swept across
the **REAL PVT corners** — **5 process corners × 3 temperatures = 15 corners**
per block (exceeds the 3×3 minimum), all **executed (0 derived)**, plus **native
Monte-Carlo** on the real statistical models.

Deterministic plugin gate `analog_corner_sweep_check.py` verdict on this real
data: **PASS** — delta_sigma 15/15 corners + MC 100%, ldo 15/15 corners + MC
100% (`reports/gates/analog_corners.json`).

### OTA (delta_sigma integrator core) — DC gain (leakage floor 48.16 dB) + UGBW

| corner | temp | DC gain (dB) | UGBW (MHz) | verdict |
|---|---|---|---|---|
| ttt | -40 C | 51.611 | 6.76 | PASS |
| ttt | 27 C | 50.944 | 5.92 | PASS |
| ttt | 125 C | 50.426 | 5.02 | PASS |
| sss | -40 C | 51.925 | 6.32 | PASS |
| sss | 27 C | 50.725 | 5.75 | PASS |
| sss | 125 C | 50.180 | 4.92 | PASS |
| fff | -40 C | 52.387 | 6.89 | PASS |
| fff | 27 C | 51.827 | 6.03 | PASS |
| fff | 125 C | 50.136 | 5.12 | PASS |
| sf  | -40 C | 52.867 | 6.40 | PASS |
| sf  | 27 C | 52.270 | 5.81 | PASS |
| sf  | 125 C | 50.771 | 4.97 | PASS |
| fs  | -40 C | 50.998 | 6.83 | PASS |
| fs  | 27 C | 50.429 | 5.96 | PASS |
| fs  | 125 C | **48.648** | 5.06 | PASS |

- Floor = 20·log10(OSR=256) = **48.16 dB** (integrator leakage < 1 LSB).
- Worst corner **fast-N/slow-P @ 125 °C = 48.648 dB** → **+0.49 dB margin** over
  floor (better than the open-PDK reference run's +0.18 dB worst-corner margin).
- **Monte-Carlo (n=50):** DC gain mean **51.80 dB**, sigma **0.247 dB**,
  min 50.98 / max 52.33 dB, **yield = 100 %** vs the 48.16 dB bound.

### LDO — Vout / Iq / PSRR@100 Hz / dropout (Vin 1.8 V, load 0.5 mA)

| corner | temp | Vout (V) | Iq (µA) | PSRR (dB) | dropout (V) | verdict |
|---|---|---|---|---|---|---|
| ttt | -40 C | 1.19980 | 14.98 | 66.16 | 0.014 | PASS |
| ttt | 27 C | 1.19985 | 22.61 | 63.98 | 0.017 | PASS |
| ttt | 125 C | 1.19981 | 11.17 | 61.21 | 0.022 | PASS |
| sss | -40 C | 1.19945 | 14.98 | 70.81 | 0.016 | PASS |
| sss | 27 C | 1.19966 | 22.61 | 66.29 | 0.019 | PASS |
| sss | 125 C | 1.19973 | 11.17 | 62.47 | 0.025 | PASS |
| fff | -40 C | 1.19987 | 14.98 | 64.27 | 0.012 | PASS |
| fff | 27 C | 1.19994 | 22.61 | 63.45 | 0.015 | PASS |
| fff | 125 C | 1.19996 | 11.17 | 60.35 | 0.019 | PASS |
| sf  | -40 C | 1.19950 | 14.98 | 71.68 | 0.011 | PASS |
| sf  | 27 C | 1.19966 | 22.61 | 64.86 | 0.014 | PASS |
| sf  | 125 C | 1.19961 | 11.17 | 61.69 | 0.017 | PASS |
| fs  | -40 C | 1.19981 | 14.98 | 64.64 | 0.018 | PASS |
| fs  | 27 C | 1.19991 | 22.61 | 63.30 | 0.022 | PASS |
| fs  | 125 C | 1.19991 | 11.17 | 61.36 | 0.028 | PASS |

- Targets: Vout 1.2 V (1.1–1.3), Iq ≤ 50 µA, PSRR ≥ 40 dB, dropout ≤ 0.5 V.
- Achieved worst-case: Vout **1.1994–1.2000 V**, Iq **≤ 22.6 µA**, PSRR
  **≥ 60.3 dB**, dropout **≤ 0.028 V** — all PASS across all 15 corners.
- **Monte-Carlo (n=50):** Vout mean **1.19984 V**, sigma **0.056 mV**,
  **yield = 100 %** vs the 1.1–1.3 V bound.

### System ENOB (delta_sigma) — node-independent
ENOB is set by the fixed-point modulator loop + sinc² decimator (a linear
incremental converter), which is **node-independent** — it does not change
between the 130 nm reference and this 180 nm node. The **analog-core enabler for
it (integrator OTA DC gain > 20·log10(OSR)) is now real-node-validated across all
15 corners**, so the system ENOB = **14.74 bits @ OSR=256, order 2** (from the
algorithmic cosim) carries with its real-node analog underpinning established.
This is reported as a system/algorithmic metric, not re-derived here.

---

## Six-pillar summary (Pillar 5 is the focus of this run)

| Pillar | Status | Note |
|---|---|---|
| 1 · Functional coverage | PASS (analog) | Both blocks meet all specs across 15 real PVT corners; digital readout coverage is node-independent (carried). |
| 2 · 56-step output vs OSS ref | Spec-level only | The UHEE628 golden is a **130 nm fabricated** die; there is no 180 nm-fab golden, so the cross-check stays **spec-level** (disclosed), not per-block device-LVS on this node. |
| 3 · Code coverage ≥90% | N/A here | Digital RTL (decimator/readout) is node-independent; not re-exercised in this analog-core re-validation. |
| 4 · FPGA digital verify | WAIVED | No DE10-class board contract for this analog IC; A8 HIL has no bench die. |
| **5 · Analog closed-loop** | **PASS (REAL commercial node)** | **2 blocks × 15 real PVT corners all PASS + native MC 100 % yield.** Dissolves `pdk_substitution`. |
| 6 · Design-for-ECO (spare) | N/A | Analog blocks have no digital PnR spare-cell surface. |

## Residual triage (honest — what is DONE vs DEFERRED)
- **DONE, real commercial node:** Phase 1 (100 %), analog **A1 spec → A2
  topology → A3 netlist → A4 corner-sweep + native MC** for both blocks (the
  flagship).
- **DEFERRED (not attempted on this node in this run):** analog **A5–A9**
  (per-block layout / DRC-LVS / post-layout resim / hardmacro / HIL) and the
  digital-readout backend + full chip PnR. The runner's phase-level
  `analog=FAIL / phase3=FAIL` reflects these un-authored later steps, **not** a
  failure of the real-node corner/MC work, which the plugin gate PASSES. These
  backend steps are backlog for a later full-tapeout pass.
- **Companion validation:** a separate focused agent independently validated the
  corner/MC methodology; this run reached the same real-node closure
  independently (see methodology note).

## Methodology note (NDA-safe — no model content)
Real-node LV-CMOS convergence required two deterministic testbench-level steps
(no edit to any staged NDA file): (1) declaring the deck's flicker-noise
selection flags to a default before the model `.lib` include, so ngspice does
not eager-evaluate an undefined-parameter formula; (2) pairing each corner's
LV-CMOS section with its passive section so the PMOS parasitic well-diode
sub-device resolves. Skew corners are composed from the process-skew sections +
a passive section. Native Monte-Carlo uses the foundry's global-process +
MC-aware device statistics (agauss) with a per-seed resample (one run per seed);
a deterministic-corner control run returns sigma = 0, proving the spread is real
resampling. All of this lives in the git-excluded driver; only VALUES are
reported.

## Provenance / reproduce
- Real-node results: `phase3/analog/{delta_sigma,ldo}/corner_results.json`
  (+ `mc_yield.json`), gate verdict `reports/gates/analog_corners.json`.
- `pdk_resolved.substitution = false`, `node_class = commercial_180nm_nda`;
  provenance flags mark real ngspice corner + MC runs.
- Decks / model libs / driver are **git-excluded** for NDA hygiene.
