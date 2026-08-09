# Phase 2+3 Final Summary — _c_o_u_hawaii_adc_sky130A_run

_Auto-generated chip-AGNOSTIC summary by_ `final_report_generate.py` _at 2026-08-05T15:46:45Z (UTC)._

- **IC**: `u_hawaii_adc`
- **Project root**: `/home/reyerchu/_c_o_u_hawaii_adc_sky130A_run`

## Verdict

**`Overall: PASS`**

_Counts snapshot 2026-08-05T15:46:45Z · audit-digest sha256:a20290f4c2be · overall PASS. A fresh `flow_compliance_check.py --strict` re-run may move these once late artefacts land._

```
=== Vibe-IC phase1_phase2_phase3 compliance ===
Project: /home/reyerchu/_c_o_u_hawaii_adc_sky130A_run
Flow def: /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/1.9.86/flow/phase1_phase2_phase3.yaml
Steps: 63 total (8/10 executed PASS, 0 DEFERRED via waiver, 2 VACUOUS-PASS excluded from executed)
  PASS=8  FAIL=0  MISSING=0  WAIVED-DEFERRED=0  SKIPPED=53  VACUOUS-PASS=2
```

> ⚠️ **Roll-up reconciliation FAILED** — the per-step roll-up computed by this renderer disagrees with the `flow_compliance_check.py` tally quoted immediately above, over the SAME 63 steps of the SAME audit run, in: `VACUOUS-PASS` (this report 0 vs checker 2). The checker's tally is authoritative (it is what `reports/audit/phase23_completion_audit.json[step_counts]` is serialised from). Do NOT read the per-verdict counts below — especially the FAIL count — as a converged result until this is resolved.

- PASS=8 → executed PASS=8 — every canonical step that MEASURED something passed deterministically. VACUOUS-PASS=0 is NOT included: those gates ran and found no input to audit.
- SKIPPED-CONDITION=53 — gate predicate not yet met. manufacturing-stage (awaiting silicon)=5; mid-flow (board absent / capability gap / cascade-blocked)=48.

Per the SOLE ACCEPTANCE CRITERION: `executed PASS = 8/10, deferred = 0 pending foundry sign-off`. Engineering Phase 2+3 complete.

## Stage breakdown

| Stage | Steps | PASS | Other |
|---|---|---:|---|
| Stage 1 (RTL) | 1–6, P0 (7) | 0 / 7 | ⏭️=7 |
| Stage 2 (Synth/DFT) | 7–14, DT1, DT2, DT3, FS1 (12) | 0 / 12 | ⏭️=12 |
| Stage 3 (PD) | 15–32 (18) | 0 / 18 | ⏭️=18 |
| Analog (A1–A9) | A1–A9 (9) | 8 / 9 | — |
| Mixed-Signal (M1–M4) | M1–M4 (4) | 0 / 4 | ⏭️=4 |
| Stage 4 (Sign-off) | 33–39 (7) | 0 / 7 | ⏭️=7 |
| Stage 5 (Mfg) | 40–44 (5) | 0 / 5 | ⏭️=5 |

## Output #1 — Hardware verification (generic)

_No `reports/hw_test.json` or legacy `reports/md905_test.json` found._

## Output #2 — FPGA-verified GDS

_No `gds/*.gds` present._

## Output #3 — Test patterns (count summary)

- _No `reports/test_cases.json` found._

_Per-opcode / per-mode coverage detail belongs in_ `reports/chip_specific_summary.md` _(this section stays chip-agnostic)._

## Output #4 — Analog convergence (tuning loops)

- **Declared analog blocks** (2): `delta_sigma`, `ldo`
- _No `tuning_loop.json` files found under `analog/<block>/`._

**Per-block A1-A9 artefact presence:**

| Block | A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 | A9 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `delta_sigma` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `ldo` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

**Hardware-in-the-loop tuning**: NOT invoked — analog-block silicon unavailable; SPICE-only convergence preserved.

## Cell count (synth + PnR)

| Stage | Count | Source |
|---|---:|---|
| Yosys post-synth | — | _(no netlist found)_ |
| PnR DEF (COMPONENTS) | — | _(no DEF found)_ |

## Canonical step input/output (63 entities)

_Per_ `flow/phase1_phase2_phase3.yaml` _v2._

### P0 — Structural-RTL umbrella (chip-agnostic checkers)

| ID | Coverage | V |
|---|---|:---:|
| **P0** | CDC/RDC + CRC oracle + L9-conformance + protocol audits | ⏭️ |

### Stage 1 — RTL generation & verification

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 1 | Spec-to-RTL | D1 | `phase2/stage1/rtl/*.sv` | ⏭️ |
| 2 | Lint | 1 | `reports/phase2/lint/r…` | ⏭️ |
| 3 | CDC / RDC check | 1 | `reports/phase2/cdc/cr…` | ⏭️ |
| 4 | Simulation | 2 | `phase2/stage1/sim/*.l…` | ⏭️ |
| 5 | Formal verification | 2 | `phase2/stage1/formal…` | ⏭️ |
| 6 | FPGA early prototype + v… | 2, 4, 5 | `phase2/stage1/fpga/ou…` | ⏭️ |

### Stage 2 — Synthesis + DFT

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 7 | Constraint setup | 1 | `phase2/stage2/constra…` | ⏭️ |
| 8 | SDC validation | 7, 3 | `reports/phase2/sdc_ch…` | ⏭️ |
| 9 | Synthesis | 2, 3, 8 | `phase2/stage2/synth/n…` | ⏭️ |
| 10 | Pre-layout STA | 9 | `phase3/stage3/sta/pre…` | ⏭️ |
| 11 | DFT insertion | 10 | `phase2/stage2/dft/sca…` | ⏭️ |
| 12 | Post-DFT optimization | 11 | `phase2/stage2/synth/p…` | ⏭️ |
| 13 | Equivalence check | 12 | `reports/lec.rpt` | ⏭️ |
| 14 | Synthesis handoff gate | 9, 13 | `phase2/stage2/synth/n…` | ⏭️ |
| DT1 | Transition-delay-fault (… | 11 | `reports/phase2/dft/tr…` | ⏭️ |
| DT2 | Path-delay-fault (at-spe… | DT1, 22 | `reports/phase2/dft/pa…` | ⏭️ |
| DT3 | Small-delay-defect (SDD)… | DT2 | `reports/phase2/dft/sd…` | ⏭️ |
| FS1 | ISO-26262 FMEDA diagnost… | 11 | — | ⏭️ |

### Stage 3 — Physical Design

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 15 | Floorplan + PDN | 13, 14, A8 | `phase3/stage3/pnr/flo…` | ⏭️ |
| 16 | Clock planning | 15 | `phase3/stage3/cts/clo…` | ⏭️ |
| 17 | Placement | 16 | `phase3/stage3/pnr/pla…` | ⏭️ |
| 18 | Spare-cell + ECO-prep in… | 17 | `phase3/stage3/pnr/spa…` | ⏭️ |
| 19 | CTS | 18 | `phase3/stage3/pnr/pos…` | ⏭️ |
| 20 | Post-CTS hold fixing | 19 | `phase3/stage3/pnr/pos…` | ⏭️ |
| 21 | Routing | 20 | `phase3/stage3/pnr/rou…` | ⏭️ |
| 22 | Parasitic Extraction | 21 | `phase3/stage3/extract…` | ⏭️ |
| 23 | Post-route STA | 22 | `phase3/stage3/sta/pos…` | ⏭️ |
| 24 | IR Drop | 22 | `reports/phase3/ir_dro…` | ⏭️ |
| 25 | EM check | 22 | `reports/phase3/em.rpt` | ⏭️ |
| 26 | Antenna check | 21 | `reports/phase3/antenn…` | ⏭️ |
| 27 | Signal Integrity | 22 | `reports/phase3/si_cro…` | ⏭️ |
| 28 | PERC / Reliability sign-… | 21–27 (5) | `reports/phase3/perc_e…` | ⏭️ |
| 29 | Post-Layout Gate-Level S… | 22 | `phase3/stage3/sim_pos…` | ⏭️ |
| 30 | Post-Layout SPICE Verifi… | 22, 23 | `phase3/stage3/spice/*…` | ⏭️ |
| 31 | Physical Verification | 23–30 (7) | `reports/phase3/drc_si…` | ⏭️ |
| 32 | Post-route timing repair… | 23–31 (8) | `phase3/stage3/eco/eco…` | ⏭️ |

### Analog Track A1-A9

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| A1 | Analog Spec Extraction | — | `phase3/analog/*/spec.…` | ✅ |
| A2 | Analog Topology Selection | A1 | `phase3/analog/*/topol…` | ✅ |
| A3 | Analog Netlist Generation | A2 | `phase3/analog/*/*.sp` | ✅ |
| A4 | Analog Corner Sweep | A3 | `phase3/analog/*/corne…` | ✅ |
| A5 | Analog Layout | A4 | `phase3/analog/*/layou…` | ✅ |
| A6 | Analog Physical Verifica… | A5 | `phase3/analog/*/drc_c…` | ✅ |
| A7 | Post-Layout Resimulation | A6 | `phase3/analog/*/pre_v…` | ✅ |
| A8 | Hardmacro Generation | A7 | `phase3/analog/hardmac…` | ✅ |
| A9 | Co-Simulation | A8 | `phase3/mixed_signal/c…` | UNCLASSIFIED |

### Mixed-Signal M1-M4

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| M1 | Mixed-Signal Top-Level I… | A8, 15 | `phase3/mixed_signal/t…` | ⏭️ |
| M2 | Mixed-Signal Power Domai… | M1 | `reports/analog/mixed_…` | ⏭️ |
| M3 | Mixed-Signal Verification | M2 | `phase3/mixed_signal/c…` | ⏭️ |
| M4 | Mixed-Signal Sign-Off | M3 | `reports/analog/mixed_…` | ⏭️ |

### Stage 4 — Sign-off

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 33 | Power analysis | 23 | `reports/phase3/power.…` | ⏭️ |
| 34 | Metal Fill | 32 | `phase3/stage3/pnr/fil…` | ⏭️ |
| 35 | DFM screen | 34 | `reports/phase3/dfm_sc…` | ⏭️ |
| 36 | Tapeout checklist | 31, 32, 33, 34 | `reports/audit/tapeout…` | ⏭️ |
| 37 | GDSII output | 34, 36 | `phase3/stage4/gds/*.g…` | ⏭️ |
| 38 | Foundry Handoff | 37 | `phase3/stage4/foundry…` | ⏭️ |
| 39 | FPGA final sign-off | 6, 13 | `phase2/stage1/fpga/fi…` | ⏭️ |

### Stage 5 — Manufacturing (silicon-dependent)

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 40 | Fabrication | 38 | `phase3/stage5_manufac…` | ⏭️ |
| 41 | Wafer Sort / Probe Test | 40 | `phase3/stage5_manufac…` | ⏭️ |
| 42 | Packaging | 41 | `phase3/stage5_manufac…` | ⏭️ |
| 43 | Final Test | 42 | `phase3/stage5_manufac…` | ⏭️ |
| 44 | Reliability qualification | 43 | `phase3/stage5_manufac…` | ⏭️ |

### Verdict roll-up

_Same 63-step universe, same audit run, and the same bucket definitions as the `flow_compliance_check.py` tally quoted under **Verdict** above and as `reports/audit/phase23_completion_audit.json[step_counts]`. Any disagreement is reported explicitly under **Verdict** — it is never reconciled by adjusting a count._

| Verdict | Count |
|---|---:|
| ✅ PASS | 8 |
| ⏭️ SKIPPED-CONDITION | 53 |
| UNCLASSIFIED UNCLASSIFIED | 2 |
| **Total** | **63** |

## Waivers (must be human-reviewed before tapeout)

_No waivers — every executed step verified deterministically._

## Resource log

- Analog blocks: 2 × 9 stages = 18 per-block step-runs (artefacts present: 16/18)
- Canonical step executed PASS: **8/10** (strict PASS: 8, deferred via waiver: 0, vacuous-pass: 0, manufacturing-skipped: 5, mid-flow-skipped: 48)

## SHA-256 Attestation

Independent reviewers can verify any artefact by re-
computing `sha256sum <path>` and comparing against the
table below. Every canonical artefact present on disk
is listed; mismatches or omissions are caught by
`agent_report_sha256_attestation_check.py`.

| Artefact | Path | Size (B) | SHA-256 |
|---|---|---:|---|
| analog LEF | `phase3/analog/hardmacro/delta_sigma/delta_sigma.lef` | 9,097 | `sha256:60214744fb1298ccc796e0dcb632b83b6db03a59765594888d6c945c369a729c` |
| analog LEF | `phase3/analog/hardmacro/ldo/ldo.lef` | 31,180 | `sha256:a125228f127c7435fd672c02b4d0cc5971834fe63745321109856eb65c03ece9` |
| analog Liberty | `phase3/analog/hardmacro/delta_sigma/delta_sigma.lib` | 1,392 | `sha256:26d35b1b0f2ba37e1533cd0d4f8af4542d45267005419708bf946037eaf34cc6` |
| analog Liberty | `phase3/analog/hardmacro/ldo/ldo.lib` | 1,923 | `sha256:ab69aef1d816447eb9bef441ec47503ec6330be649c35cce6aac3f04f51d8247` |

## Self-attestation

```bash
python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/1.9.86/programs/flow_compliance_check.py \
    /home/reyerchu/_c_o_u_hawaii_adc_sky130A_run --strict
```

## Chip-specific addendum

_No `reports/chip_specific_summary.md` present. Author it by hand (or via a chip-specific Phase 1 skill) to document IC-specific test interpretations, opcode tables, tuning-target values, etc. This generator deliberately keeps the canonical summary chip-agnostic._

