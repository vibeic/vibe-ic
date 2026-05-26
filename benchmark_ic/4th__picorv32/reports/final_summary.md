# Phase 2+3 Final Summary — _vibeic_phase3_picorv32

_Auto-generated chip-AGNOSTIC summary by_ `final_report_generate.py` _at 2026-05-26T02:50:35Z (UTC)._

- **IC**: `(unknown — fill in via L1_DATASHEET.json[ic_name])`
- **Project root**: `/home/reyerchu/AI_IC_design/_vibeic_phase3_picorv32`

## Verdict

**`Overall: FAIL`**

```
=== Vibe-IC phase1_phase2_phase3 compliance ===
Project: /home/reyerchu/AI_IC_design/_vibeic_phase3_picorv32
Flow def: /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml
Steps: 55 total (19/38 executed PASS, 0 DEFERRED via waiver)
  PASS=18  FAIL=8  MISSING=11  WAIVED-DEFERRED=0  SKIPPED=17  VACUOUS-PASS=1
```

- PASS=17 — every executed canonical step passed deterministically.
- SKIPPED-CONDITION=17 — gate predicate not yet met (e.g., manufacturing steps awaiting silicon).
- VACUOUS-PASS=1 — gate accepts the present project shape; check whether it should be a real PASS for your flow.
- **FAIL=8** — blocking; do not claim PASS.

Per the SOLE ACCEPTANCE CRITERION: `executed PASS = 17/17, deferred = 0 pending foundry sign-off`. Engineering Phase 2+3 INCOMPLETE — fix FAILs before claiming.

## Stage breakdown

| Stage | Steps | PASS | Other |
|---|---|---:|---|
| Stage 1 (RTL) | 1–6, P0 (7) | 3 / 7 | ❌=4 |
| Stage 2 (Synth/DFT) | 7–13 (7) | 2 / 7 | ❌=2 ❓=3 |
| Stage 3 (PD) | 14–30 (17) | 9 / 17 | 🟦=1 ❌=1 ❓=7 |
| Analog (A1–A9) | A1–A9 (9) | 0 / 9 | ⏭️=9 |
| Mixed-Signal (M1–M4) | M1–M4 (4) | 0 / 4 | ⏭️=4 |
| Stage 4 (Sign-off) | 31–36 (6) | 4 / 6 | ❌=1 ❓=1 |
| Stage 5 (Mfg) | 37–40 (4) | 0 / 4 | ⏭️=4 |

## Output #1 — Hardware verification (generic)

_No `reports/hw_test.json` or legacy `reports/md905_test.json` found._

## Output #2 — FPGA-verified GDS

- **GDS**: `phase3/stage4/gds/chip_top.gds` (1,288,338 B)
- **GDS SHA-256**: `2afed26c55d8da68b4813e03f0bbaefaa05a0895f70e5f05992e6d54369e9d72`
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

_No `analog/analog_block_list.json` found — pure-digital project, or analog track not run._

## Cell count (synth + PnR)

| Stage | Count | Source |
|---|---:|---|
| Yosys post-synth | 0 | `phase2/stage2/synth/netlist.v` |
| PnR DEF (COMPONENTS) | 7531 | `phase3/stage3/pnr/routed.def` |

## Canonical step input/output (55 entities)

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
| 5 | Formal verification | 2 | `phase2/stage1/formal…` | ❌ |
| 6 | FPGA early prototype + v… | 2, 4, 5 | `phase2/stage1/fpga/ou…` | ❌ |

### Stage 2 — Synthesis + DFT

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 7 | Constraint setup | 1 | `phase2/stage2/constra…` | ✅ |
| 8 | SDC validation | 7 | `reports/phase2/sdc_ch…` | ✅ |
| 9 | Synthesis | 2, 3, 8 | `phase2/stage2/synth/n…` | ❌ |
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
| 18 | CTS | 17 | `phase3/stage3/pnr/pos…` | ✅ |
| 19 | Post-CTS hold fixing | 18 | `phase3/stage3/pnr/pos…` | ✅ |
| 20 | Routing | 19 | `phase3/stage3/pnr/rou…` | ✅ |
| 21 | Parasitic Extraction | 20 | `phase3/stage3/extract…` | ❓ |
| 22 | Post-route STA | 21 | `phase3/stage3/sta/pos…` | ❌ |
| 23 | IR Drop | 21 | `reports/phase3/ir_dro…` | ❓ |
| 24 | EM check | 21 | `reports/phase3/em.rpt` | ❓ |
| 25 | Antenna check | 20 | `reports/phase3/antenn…` | ❓ |
| 26 | Signal Integrity | 21 | `reports/phase3/si_cro…` | ❓ |
| 27 | Post-Layout Gate-Level S… | 21 | `phase3/stage3/sim_pos…` | ✅ |
| 28 | Post-Layout SPICE Verifi… | 21, 22 | `phase3/stage3/spice/*…` | ❓ |
| 29 | Physical Verification | 22–28 (7) | `reports/phase3/drc_si…` | ❓ |
| 30 | ECO | 22–29 (8) | `phase3/stage3/eco/eco…` | ✅ |

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
| 31 | Power analysis | 22 | `reports/phase3/power.…` | ✅ |
| 32 | Metal Fill | 30 | `phase3/stage3/pnr/fil…` | ❓ |
| 33 | Tapeout checklist | 29, 30, 31, 32 | `reports/audit/tapeout…` | ✅ |
| 34 | GDSII output | 32, 33 | `phase3/stage4/gds/*.g…` | ✅ |
| 35 | Foundry Handoff | 34 | `phase3/stage4/foundry…` | ✅ |
| 36 | FPGA final sign-off | 13 | `phase2/stage1/fpga/fi…` | ❌ |

### Stage 5 — Manufacturing (silicon-dependent)

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 37 | Fabrication | 35 | `phase3/stage5_manufac…` | ⏭️ |
| 38 | Wafer Sort / Probe Test | 37 | `phase3/stage5_manufac…` | ⏭️ |
| 39 | Packaging | 38 | `phase3/stage5_manufac…` | ⏭️ |
| 40 | Final Test | 39 | `phase3/stage5_manufac…` | ⏭️ |

### Verdict roll-up

| Verdict | Count |
|---|---:|
| ✅ PASS | 17 |
| 🟦 VACUOUS-PASS | 1 |
| ⏭️ SKIPPED-CONDITION | 17 |
| ❌ FAIL | 8 |
| ❓ MISSING | 12 |
| **Total** | **55** |

## Waivers (must be human-reviewed before tapeout)

### Step ? — `TAPEOUT-AUTOGEN-LVS`

- **Approver**: `—`    **review_required**: ✅
- **Evidence**: `['reports/orchestrator/phase3_one_shot.json#steps[name=lvs]']`

```
(no reason given — waiver is INVALID)
```

## Resource log

- DEF COMPONENTS post-PnR: **7531**
- Canonical step PASS: **17/38** (deferred via waiver: 0, vacuous-pass: 1, manufacturing-skipped: 17)

## SHA-256 Attestation

Independent reviewers can verify any artefact by re-
computing `sha256sum <path>` and comparing against the
table below. Every canonical artefact present on disk
is listed; mismatches or omissions are caught by
`agent_report_sha256_attestation_check.py`.

| Artefact | Path | Size (B) | SHA-256 |
|---|---|---:|---|
| chip GDS | `phase3/stage4/gds/chip_top.gds` | 1,288,338 | `sha256:2afed26c55d8da68b4813e03f0bbaefaa05a0895f70e5f05992e6d54369e9d72` |
| foundry GDS | `phase3/stage4/foundry_handoff/chip_top.gds` | 1,288,338 | `sha256:2afed26c55d8da68b4813e03f0bbaefaa05a0895f70e5f05992e6d54369e9d72` |
| foundry GDS | `phase3/stage4/foundry_handoff/scribe_line_layout.gds` | 137 | `sha256:aa06450c7345ae3e71d83f98b09879db39dd45f091515a377557320c565e3122` |
| synth netlist | `phase2/stage2/synth/chip_top_synth.v` | 1,013,861 | `sha256:4a31d246efd2552cedec0ef9325388ccf138ef1f94c952e425810d9ed097a5ca` |
| synth netlist | `phase2/stage2/synth/netlist.v` | 2,338,117 | `sha256:e619ba4b0b9cab5417a47c5b159c9e184feeb0ae1cab460951f3fabc1664e69c` |
| synth netlist | `phase2/stage2/synth/netlist_yosys.v` | 2,338,117 | `sha256:e619ba4b0b9cab5417a47c5b159c9e184feeb0ae1cab460951f3fabc1664e69c` |
| PnR netlist | `phase3/stage3/pnr/chip_top_pnr.v` | 1,028,453 | `sha256:10f1a03edd120548408fcd28fa452d7f71334c2b549b1e926b337fc7cbba4afe` |

## Self-attestation

```bash
python3 /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/flow_compliance_check.py \
    /home/reyerchu/AI_IC_design/_vibeic_phase3_picorv32 --strict
```

## Chip-specific addendum

_No `reports/chip_specific_summary.md` present. Author it by hand (or via a chip-specific Phase-2a skill) to document IC-specific test interpretations, opcode tables, tuning-target values, etc. This generator deliberately keeps the canonical summary chip-agnostic._

