# Phase 2+3 Final Summary — subservient_v0125_reverify

_Auto-generated chip-AGNOSTIC summary by_ `final_report_generate.py` _at 2026-05-28T01:43:49Z (UTC)._

- **IC**: `(unknown — fill in via L1_DATASHEET.json[ic_name])`
- **Project root**: `/home/reyerchu/AI_IC_design/subservient_v0125_reverify`

## Verdict

**`Overall: FAIL`**

```
=== Vibe-IC phase1_phase2_phase3 compliance ===
Project: /home/reyerchu/AI_IC_design/subservient_v0125_reverify
Flow def: /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml
Steps: 56 total (22/39 executed PASS, 0 DEFERRED via waiver)
  PASS=21  FAIL=6  MISSING=11  WAIVED-DEFERRED=0  SKIPPED=17  VACUOUS-PASS=1
```

- PASS=20 — every executed canonical step passed deterministically.
- SKIPPED-CONDITION=17 — gate predicate not yet met (e.g., manufacturing steps awaiting silicon).
- VACUOUS-PASS=1 — gate accepts the present project shape; check whether it should be a real PASS for your flow.
- **FAIL=6** — blocking; do not claim PASS.

Per the SOLE ACCEPTANCE CRITERION: `executed PASS = 20/20, deferred = 0 pending foundry sign-off`. Engineering Phase 2+3 INCOMPLETE — fix FAILs before claiming.

## Stage breakdown

| Stage | Steps | PASS | Other |
|---|---|---:|---|
| Stage 1 (RTL) | 1–6, P0 (7) | 4 / 7 | ❌=3 |
| Stage 2 (Synth/DFT) | 7–13 (7) | 3 / 7 | ❌=1 ❓=3 |
| Stage 3 (PD) | 14–31 (18) | 10 / 18 | 🟦=1 ❌=1 ❓=7 |
| Analog (A1–A9) | A1–A9 (9) | 0 / 9 | ⏭️=9 |
| Mixed-Signal (M1–M4) | M1–M4 (4) | 0 / 4 | ⏭️=4 |
| Stage 4 (Sign-off) | 32–37 (6) | 4 / 6 | ❌=1 ❓=1 |
| Stage 5 (Mfg) | 38–41 (4) | 0 / 4 | ⏭️=4 |

## Output #1 — Hardware verification (generic)

_No `reports/hw_test.json` or legacy `reports/md905_test.json` found._

## Output #2 — FPGA-verified GDS

- **GDS**: `phase3/stage4/gds/chip_top.gds` (1,121,270 B)
- **GDS SHA-256**: `05531211e64b0e521c33fe4b8bb94afa293f720c2644153f895bbf65ee346c71`
- **Physical verification**: drc_signoff=`(report missing)`, lvs=`(report missing)`, erc=`(report missing)`
- **Auxiliary signoff reports** (1): `reports/phase3/power.json`

## Output #3 — Test patterns (count summary)

- _No `reports/test_cases.json` found._
- **sim_full_stack vectors**: 8 / 8 PASS
- **Distinct opcodes / commands exercised**: 5
- **Distinct non-padding bytes**: 10
- _sim_full_stack source_: `phase2/stage1/sim_full_stack/results.json`

_Per-opcode / per-mode coverage detail belongs in_ `reports/chip_specific_summary.md` _(this section stays chip-agnostic)._

## Output #4 — Analog convergence (tuning loops)

- **Declared analog blocks** (2): `dac`, `esd`
- _No `tuning_loop.json` files found under `analog/<block>/`._

**Per-block A1-A9 artefact presence:**

| Block | A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 | A9 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `dac` | — | — | — | — | — | — | — | — | — |
| `esd` | — | — | — | — | — | — | — | — | — |

**Hardware-in-the-loop tuning**: NOT invoked — analog-block silicon unavailable; SPICE-only convergence preserved.

## Cell count (synth + PnR)

| Stage | Count | Source |
|---|---:|---|
| Yosys post-synth | 0 | `phase2/stage2/synth/netlist.v` |
| PnR DEF (COMPONENTS) | 4105 | `phase3/stage3/pnr/routed.def` |

## Canonical step input/output (56 entities)

_Per_ `flow/phase1_phase2_phase3.yaml` _v2._

### P0 — Structural-RTL umbrella (chip-agnostic checkers)

| ID | Coverage | V |
|---|---|:---:|
| **P0** | CDC/RDC + CRC oracle + L9-conformance + protocol audits | ❌ |

### Stage 1 — RTL generation & verification

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 1 | Spec-to-RTL | — | `phase2/stage1/rtl/*.sv` | ✅ |
| 2 | Lint | 1 | `reports/phase2/lint/r…` | ❌ |
| 3 | CDC / RDC check | 1 | `reports/phase2/cdc/cr…` | ✅ |
| 4 | Simulation | 2 | `phase2/stage1/sim/*.l…` | ✅ |
| 5 | Formal verification | 2 | `phase2/stage1/formal…` | ✅ |
| 6 | FPGA early prototype + v… | 2, 4, 5 | `phase2/stage1/fpga/ou…` | ❌ |

### Stage 2 — Synthesis + DFT

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 7 | Constraint setup | 1 | `phase2/stage2/constra…` | ✅ |
| 8 | SDC validation | 7 | `reports/phase2/sdc_ch…` | ✅ |
| 9 | Synthesis | 2, 3, 8 | `phase2/stage2/synth/n…` | ✅ |
| 10 | Pre-layout STA | 9 | `phase3/stage3/sta/pre…` | ❌ |
| 11 | DFT insertion | 10 | `phase2/stage2/dft/sca…` | ❓ |
| 12 | Post-DFT optimization | 11 | `phase2/stage2/synth/p…` | ❓ |
| 13 | Equivalence check | 12 | `reports/lec.rpt` | ❓ |

### Stage 3 — Physical Design

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 14 | pre-PnR Yosys gate | 9, 13 | `phase2/stage2/synth/n…` | 🟦 |
| 15 | Floorplan + PDN | 13, 14, A8 | `phase3/stage3/pnr/flo…` | ✅ |
| 16 | Clock planning | 15 | `phase3/stage3/cts/clo…` | ✅ |
| 17 | Placement | 16 | `phase3/stage3/pnr/pla…` | ✅ |
| 18 | Spare-cell + ECO-prep in… | 17 | `phase3/stage3/pnr/spa…` | ✅ |
| 19 | CTS | 18 | `phase3/stage3/pnr/pos…` | ✅ |
| 20 | Post-CTS hold fixing | 19 | `phase3/stage3/pnr/pos…` | ✅ |
| 21 | Routing | 20 | `phase3/stage3/pnr/rou…` | ✅ |
| 22 | Parasitic Extraction | 21 | `phase3/stage3/extract…` | ❓ |
| 23 | Post-route STA | 22 | `phase3/stage3/sta/pos…` | ❌ |
| 24 | IR Drop | 22 | `reports/phase3/ir_dro…` | ❓ |
| 25 | EM check | 22 | `reports/phase3/em.rpt` | ❓ |
| 26 | Antenna check | 21 | `reports/phase3/antenn…` | ❓ |
| 27 | Signal Integrity | 22 | `reports/phase3/si_cro…` | ❓ |
| 28 | Post-Layout Gate-Level S… | 22 | `phase3/stage3/sim_pos…` | ✅ |
| 29 | Post-Layout SPICE Verifi… | 22, 23 | `phase3/stage3/spice/*…` | ❓ |
| 30 | Physical Verification | 23–29 (7) | `reports/phase3/drc_si…` | ❓ |
| 31 | ECO | 23–30 (8) | `phase3/stage3/eco/eco…` | ✅ |

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
| 32 | Power analysis | 23 | `reports/phase3/power.…` | ✅ |
| 33 | Metal Fill | 31 | `phase3/stage3/pnr/fil…` | ❓ |
| 34 | Tapeout checklist | 30, 31, 32, 33 | `reports/audit/tapeout…` | ✅ |
| 35 | GDSII output | 33, 34 | `phase3/stage4/gds/*.g…` | ✅ |
| 36 | Foundry Handoff | 35 | `phase3/stage4/foundry…` | ✅ |
| 37 | FPGA final sign-off | 13 | `phase2/stage1/fpga/fi…` | ❌ |

### Stage 5 — Manufacturing (silicon-dependent)

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 38 | Fabrication | 36 | `phase3/stage5_manufac…` | ⏭️ |
| 39 | Wafer Sort / Probe Test | 38 | `phase3/stage5_manufac…` | ⏭️ |
| 40 | Packaging | 39 | `phase3/stage5_manufac…` | ⏭️ |
| 41 | Final Test | 40 | `phase3/stage5_manufac…` | ⏭️ |

### Verdict roll-up

| Verdict | Count |
|---|---:|
| ✅ PASS | 20 |
| 🟦 VACUOUS-PASS | 1 |
| ⏭️ SKIPPED-CONDITION | 17 |
| ❌ FAIL | 6 |
| ❓ MISSING | 12 |
| **Total** | **56** |

## Waivers (must be human-reviewed before tapeout)

### Step ? — `TAPEOUT-AUTOGEN-LVS`

- **Approver**: `—`    **review_required**: ✅
- **Evidence**: `['reports/orchestrator/phase3_one_shot.json#steps[name=lvs]']`

```
(no reason given — waiver is INVALID)
```

## Resource log

- DEF COMPONENTS post-PnR: **4105**
- Analog blocks: 2 × 9 stages = 18 per-block step-runs (artefacts present: 0/18)
- Canonical step PASS: **20/39** (deferred via waiver: 0, vacuous-pass: 1, manufacturing-skipped: 17)

## SHA-256 Attestation

Independent reviewers can verify any artefact by re-
computing `sha256sum <path>` and comparing against the
table below. Every canonical artefact present on disk
is listed; mismatches or omissions are caught by
`agent_report_sha256_attestation_check.py`.

| Artefact | Path | Size (B) | SHA-256 |
|---|---|---:|---|
| chip GDS | `phase3/stage4/gds/chip_top.gds` | 1,121,270 | `sha256:05531211e64b0e521c33fe4b8bb94afa293f720c2644153f895bbf65ee346c71` |
| foundry GDS | `phase3/stage4/foundry_handoff/chip_top.gds` | 1,121,270 | `sha256:05531211e64b0e521c33fe4b8bb94afa293f720c2644153f895bbf65ee346c71` |
| foundry GDS | `phase3/stage4/foundry_handoff/chip_top.magic_merged.gds` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| foundry GDS | `phase3/stage4/foundry_handoff/scribe_line_layout.gds` | 137 | `sha256:aa06450c7345ae3e71d83f98b09879db39dd45f091515a377557320c565e3122` |
| synth netlist | `phase2/stage2/synth/_dlatch_map.v` | 192 | `sha256:d22ec196b64163ed3f84528bfd444723b1a5bb262d3047801457e324a5da16eb` |
| synth netlist | `phase2/stage2/synth/chip_top_synth.v` | 669,189 | `sha256:6c2f346516358461aabd75326e485bd46439c394d7857f1fb44503c1f2904ac0` |
| synth netlist | `phase2/stage2/synth/netlist.v` | 1,335,988 | `sha256:08d0da79ad1ec67ee8d7ad15ee460de8f1ed31b9b43f91a92eb6a90d0dd37e26` |
| synth netlist | `phase2/stage2/synth/netlist_yosys.v` | 1,335,987 | `sha256:74e37493486e0c52bd0c5b514ee5ae569d53edbb92c8aa6db1d260d60cba85f4` |
| PnR netlist | `phase3/stage3/pnr/chip_top_pnr.v` | 611,580 | `sha256:e92f7b18d109d26b21055871005f18f573fc2e39841012046c1ee6ce61f9fcc1` |

## Self-attestation

```bash
python3 /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/flow_compliance_check.py \
    /home/reyerchu/AI_IC_design/subservient_v0125_reverify --strict
```

## Chip-specific addendum

_No `reports/chip_specific_summary.md` present. Author it by hand (or via a chip-specific Phase-2a skill) to document IC-specific test interpretations, opcode tables, tuning-target values, etc. This generator deliberately keeps the canonical summary chip-agnostic._

