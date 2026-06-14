# Phase 2+3 Final Summary — opentitan_aes

_Auto-generated chip-AGNOSTIC summary by_ `final_report_generate.py` _at 2026-06-13T17:01:22Z (UTC)._

- **IC**: `opentitan_aes`
- **Project root**: `/home/reyerchu/AI_IC_design/_bench6_v100_r1/opentitan_aes`

## Verdict

**`Overall: FAIL`**

_Counts snapshot 2026-06-13T17:01:22Z · audit-digest sha256:9805224317cb · overall FAIL. A fresh `flow_compliance_check.py --strict` re-run may move these once late artefacts land._

```
=== Vibe-IC phase1_phase2_phase3 compliance ===
Project: /home/reyerchu/AI_IC_design/_bench6_v100_r1/opentitan_aes
Flow def: /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/1.0.0/flow/phase1_phase2_phase3.yaml
Steps: 59 total (4/35 executed PASS, 1 DEFERRED via waiver)
  PASS=3  FAIL=6  MISSING=25 (25 blocked-by-upstream of step 3)  WAIVED-DEFERRED=1  SKIPPED=23  VACUOUS-PASS=1
```

- PASS=3 (+VACUOUS-PASS=1 → executed PASS=4) — every executed canonical step passed deterministically.
- SKIPPED-CONDITION=23 — gate predicate not yet met (e.g., manufacturing steps awaiting silicon).
- VACUOUS-PASS=1 — gate accepts the present project shape; check whether it should be a real PASS for your flow.
- **FAIL=6** — blocking; do not claim PASS.

Per the SOLE ACCEPTANCE CRITERION: `executed PASS = 4/36, deferred = 0 pending foundry sign-off`. Engineering Phase 2+3 INCOMPLETE — fix FAILs before claiming.

## Stage breakdown

| Stage | Steps | PASS | Other |
|---|---|---:|---|
| Stage 1 (RTL) | 1–6, P0 (7) | 2 / 7 | ❌=5 |
| Stage 2 (Synth/DFT) | 7–14 (8) | 2 / 8 | ⏭️=3 🟦=1 ❓=3 |
| Stage 3 (PD) | 15–32 (18) | 0 / 18 | ⏭️=2 ❓=16 |
| Analog (A1–A9) | A1–A9 (9) | 0 / 9 | ⏭️=9 |
| Mixed-Signal (M1–M4) | M1–M4 (4) | 0 / 4 | ⏭️=4 |
| Stage 4 (Sign-off) | 33–39 (7) | 0 / 7 | ❌=1 ❓=6 |
| Stage 5 (Mfg) | 40–44 (5) | 0 / 5 | ⏭️=5 |

## Output #1 — Hardware verification (generic)

_No `reports/hw_test.json` or legacy `reports/md905_test.json` found._

## Output #2 — FPGA-verified GDS

_No `gds/*.gds` present._

## Output #3 — Test patterns (count summary)

- _No `reports/test_cases.json` found._
- **sim_full_stack vectors**: 0 / 8 PASS
- **Distinct opcodes / commands exercised**: 0
- **Distinct non-padding bytes**: 16
- _sim_full_stack source_: `phase2/stage1/sim_full_stack/results.json`

_Per-opcode / per-mode coverage detail belongs in_ `reports/chip_specific_summary.md` _(this section stays chip-agnostic)._

## Output #4 — Analog convergence (tuning loops)

_No `analog/analog_block_list.json` found — pure-digital project, or analog track not run._

## Cell count (synth + PnR)

| Stage | Count | Source |
|---|---:|---|
| Yosys post-synth | 0 | `phase2/stage2/synth/netlist.v` |
| PnR DEF (COMPONENTS) | — | _(no DEF found)_ |

## Canonical step input/output (59 entities)

_Per_ `flow/phase1_phase2_phase3.yaml` _v2._

### P0 — Structural-RTL umbrella (chip-agnostic checkers)

| ID | Coverage | V |
|---|---|:---:|
| **P0** | CDC/RDC + CRC oracle + L9-conformance + protocol audits | ❌ |

### Stage 1 — RTL generation & verification

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 1 | Spec-to-RTL | — | `phase2/stage1/rtl/*.sv` | ✅ |
| 2 | Lint | 1 | `reports/phase2/lint/r…` | ✅ |
| 3 | CDC / RDC check | 1 | `reports/phase2/cdc/cr…` | ❌ |
| 4 | Simulation | 2 | `phase2/stage1/sim/*.l…` | ❌ |
| 5 | Formal verification | 2 | `phase2/stage1/formal…` | ❌ |
| 6 | FPGA early prototype + v… | 2, 4, 5 | `phase2/stage1/fpga/ou…` | ❌ |

### Stage 2 — Synthesis + DFT

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 7 | Constraint setup | 1 | `phase2/stage2/constra…` | ❓ |
| 8 | SDC validation | 7 | `reports/phase2/sdc_ch…` | ❓ |
| 9 | Synthesis | 2, 3, 8 | `phase2/stage2/synth/n…` | ✅ |
| 10 | Pre-layout STA | 9 | `phase3/stage3/sta/pre…` | ❓ |
| 11 | DFT insertion | 10 | `phase2/stage2/dft/sca…` | ⏭️ |
| 12 | Post-DFT optimization | 11 | `phase2/stage2/synth/p…` | ⏭️ |
| 13 | Equivalence check | 12 | `reports/lec.rpt` | ⏭️ |
| 14 | Synthesis handoff gate | 9, 13 | `phase2/stage2/synth/n…` | 🟦 |

### Stage 3 — Physical Design

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 15 | Floorplan + PDN | 13, 14, A8 | `phase3/stage3/pnr/flo…` | ❓ |
| 16 | Clock planning | 15 | `phase3/stage3/cts/clo…` | ❓ |
| 17 | Placement | 16 | `phase3/stage3/pnr/pla…` | ❓ |
| 18 | Spare-cell + ECO-prep in… | 17 | `phase3/stage3/pnr/spa…` | ❓ |
| 19 | CTS | 18 | `phase3/stage3/pnr/pos…` | ❓ |
| 20 | Post-CTS hold fixing | 19 | `phase3/stage3/pnr/pos…` | ❓ |
| 21 | Routing | 20 | `phase3/stage3/pnr/rou…` | ❓ |
| 22 | Parasitic Extraction | 21 | `phase3/stage3/extract…` | ❓ |
| 23 | Post-route STA | 22 | `phase3/stage3/sta/pos…` | ❓ |
| 24 | IR Drop | 22 | `reports/phase3/ir_dro…` | ❓ |
| 25 | EM check | 22 | `reports/phase3/em.rpt` | ❓ |
| 26 | Antenna check | 21 | `reports/phase3/antenn…` | ❓ |
| 27 | Signal Integrity | 22 | `reports/phase3/si_cro…` | ❓ |
| 28 | PERC / Reliability sign-… | 21–27 (5) | `reports/phase3/perc_e…` | ❓ |
| 29 | Post-Layout Gate-Level S… | 22 | `phase3/stage3/sim_pos…` | ⏭️ |
| 30 | Post-Layout SPICE Verifi… | 22, 23 | `phase3/stage3/spice/*…` | ⏭️ |
| 31 | Physical Verification | 23–30 (7) | `reports/phase3/drc_si…` | ❓ |
| 32 | ECO | 23–31 (8) | `phase3/stage3/eco/eco…` | ❓ |

### Analog Track A1-A9

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| A1 | Analog Spec Extraction | — | `phase1/analog/*/spec.…` | ⏭️ |
| A2 | Analog Topology Selection | A1 | `phase2/analog/*/topol…` | ⏭️ |
| A3 | Analog Netlist Generation | A2 | `phase2/analog/*/*.sp` | ⏭️ |
| A4 | Analog Corner Sweep | A3 | `phase2/analog/*/corne…` | ⏭️ |
| A5 | Analog Layout | A4 | `phase3/analog/*/layou…` | ⏭️ |
| A6 | Analog Physical Verifica… | A5 | `phase3/analog/*/drc_c…` | ⏭️ |
| A7 | Post-Layout Resimulation | A6 | `phase3/analog/*/pre_v…` | ⏭️ |
| A8 | Hardmacro Generation | A7 | `phase3/analog/hardmac…` | ⏭️ |
| A9 | Co-Simulation / HW Verif… | A8 | `phase3/mixed_signal/c…` | ⏭️ |

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
| 33 | Power analysis | 23 | `reports/phase3/power.…` | ❓ |
| 34 | Metal Fill | 32 | `phase3/stage3/pnr/fil…` | ❓ |
| 35 | DFM screen | 34 | `reports/phase3/dfm_sc…` | ❓ |
| 36 | Tapeout checklist | 31, 32, 33, 34 | `reports/audit/tapeout…` | ❓ |
| 37 | GDSII output | 34, 36 | `phase3/stage4/gds/*.g…` | ❓ |
| 38 | Foundry Handoff | 37 | `phase3/stage4/foundry…` | ❓ |
| 39 | FPGA final sign-off | 13 | `phase2/stage1/fpga/fi…` | ❌ |

### Stage 5 — Manufacturing (silicon-dependent)

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 40 | Fabrication | 38 | `phase3/stage5_manufac…` | ⏭️ |
| 41 | Wafer Sort / Probe Test | 40 | `phase3/stage5_manufac…` | ⏭️ |
| 42 | Packaging | 41 | `phase3/stage5_manufac…` | ⏭️ |
| 43 | Final Test | 42 | `phase3/stage5_manufac…` | ⏭️ |
| 44 | Reliability qualification | 43 | `phase3/stage5_manufac…` | ⏭️ |

### Verdict roll-up

| Verdict | Count |
|---|---:|
| ✅ PASS | 3 |
| 🟦 VACUOUS-PASS | 1 |
| ⏭️ SKIPPED-CONDITION | 23 |
| ❌ FAIL | 6 |
| ❓ MISSING | 26 |
| **Total** | **59** |

## Waivers (must be human-reviewed before tapeout)

_No waivers — every executed step verified deterministically._

## Resource log

- Canonical step executed PASS: **4/36** (strict PASS: 3, deferred via waiver: 0, vacuous-pass: 1, manufacturing-skipped: 23)

## SHA-256 Attestation

Independent reviewers can verify any artefact by re-
computing `sha256sum <path>` and comparing against the
table below. Every canonical artefact present on disk
is listed; mismatches or omissions are caught by
`agent_report_sha256_attestation_check.py`.

| Artefact | Path | Size (B) | SHA-256 |
|---|---|---:|---|
| synth netlist | `phase2/stage2/synth/chip_top_sv2v.v` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| synth netlist | `phase2/stage2/synth/netlist.v` | 11,973,774 | `sha256:9bd62ecdc1a4af129eccb7f0774cb3951f5ed9db96d60add3f97c1f38ad4fefc` |
| synth netlist | `phase2/stage2/synth/netlist_yosys.v` | 11,973,774 | `sha256:9bd62ecdc1a4af129eccb7f0774cb3951f5ed9db96d60add3f97c1f38ad4fefc` |

## Self-attestation

```bash
python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/1.0.0/programs/flow_compliance_check.py \
    /home/reyerchu/AI_IC_design/_bench6_v100_r1/opentitan_aes --strict
```

## Chip-specific addendum

_No `reports/chip_specific_summary.md` present. Author it by hand (or via a chip-specific Phase 1 skill) to document IC-specific test interpretations, opcode tables, tuning-target values, etc. This generator deliberately keeps the canonical summary chip-agnostic._

