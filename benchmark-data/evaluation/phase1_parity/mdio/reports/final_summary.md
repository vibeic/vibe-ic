# Phase 2+3 Final Summary — mdio

_Auto-generated chip-AGNOSTIC summary by_ `final_report_generate.py` _at 2026-06-01T20:10:21Z (UTC)._

- **IC**: `(unknown — fill in via L1_DATASHEET.json[ic_name])`
- **Project root**: `/home/reyerchu/vibe-ic/.claude/worktrees/land-cascade/benchmark_phase1/mdio`

## Verdict

**`Overall: FAIL`**

```
=== Vibe-IC phase1_phase2_phase3 compliance ===
Project: /home/reyerchu/vibe-ic/.claude/worktrees/land-cascade/benchmark_phase1/mdio
Flow def: /home/reyerchu/vibe-ic/.claude/worktrees/land-cascade/vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml
Steps: 56 total (10/39 executed PASS, 0 DEFERRED via waiver)
  PASS=9  FAIL=2  MISSING=27  WAIVED-DEFERRED=0  SKIPPED=17  VACUOUS-PASS=1
```

- PASS=8 — every executed canonical step passed deterministically.
- SKIPPED-CONDITION=17 — gate predicate not yet met (e.g., manufacturing steps awaiting silicon).
- VACUOUS-PASS=1 — gate accepts the present project shape; check whether it should be a real PASS for your flow.
- **FAIL=2** — blocking; do not claim PASS.

Per the SOLE ACCEPTANCE CRITERION: `executed PASS = 8/8, deferred = 0 pending foundry sign-off`. Engineering Phase 2+3 INCOMPLETE — fix FAILs before claiming.

## Stage breakdown

| Stage | Steps | PASS | Other |
|---|---|---:|---|
| Stage 1 (RTL) | 1–6, P0 (7) | 6 / 7 | ❌=1 |
| Stage 2 (Synth/DFT) | 7–13 (7) | 1 / 7 | ❓=6 |
| Stage 3 (PD) | 14–31 (18) | 1 / 18 | 🟦=1 ❓=17 |
| Analog (A1–A9) | A1–A9 (9) | 0 / 9 | ⏭️=9 |
| Mixed-Signal (M1–M4) | M1–M4 (4) | 0 / 4 | ⏭️=4 |
| Stage 4 (Sign-off) | 32–37 (6) | 1 / 6 | ❌=1 ❓=4 |
| Stage 5 (Mfg) | 38–41 (4) | 0 / 4 | ⏭️=4 |

## Output #1 — Hardware verification (generic)

_No `reports/hw_test.json` or legacy `reports/md905_test.json` found._

## Output #2 — FPGA-verified GDS

- **GDS**: `phase3/stage4/gds/chip_top.gds` (961,708 B)
- **GDS SHA-256**: `9a23e23d61e925f19bd28a05fefe62fa67073289484eab890b84156ac79a2679`
- **Physical verification**: drc_signoff=`(report missing)`, lvs=`(report missing)`, erc=`(report missing)`

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
| PnR DEF (COMPONENTS) | — | _(no DEF found)_ |

## Canonical step input/output (56 entities)

_Per_ `flow/phase1_phase2_phase3.yaml` _v2._

### P0 — Structural-RTL umbrella (chip-agnostic checkers)

| ID | Coverage | V |
|---|---|:---:|
| **P0** | CDC/RDC + CRC oracle + L9-conformance + protocol audits | ✅ |

### Stage 1 — RTL generation & verification

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 1 | Spec-to-RTL | — | `phase2/stage1/rtl/*.sv` | ✅ |
| 2 | Lint | 1 | `reports/phase2/lint/r…` | ✅ |
| 3 | CDC / RDC check | 1 | `reports/phase2/cdc/cr…` | ✅ |
| 4 | Simulation | 2 | `phase2/stage1/sim/*.l…` | ✅ |
| 5 | Formal verification | 2 | `phase2/stage1/formal…` | ✅ |
| 6 | FPGA early prototype + v… | 2, 4, 5 | `phase2/stage1/fpga/ou…` | ❌ |

### Stage 2 — Synthesis + DFT

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 7 | Constraint setup | 1 | `phase2/stage2/constra…` | ❓ |
| 8 | SDC validation | 7 | `reports/phase2/sdc_ch…` | ❓ |
| 9 | Synthesis | 2, 3, 8 | `phase2/stage2/synth/n…` | ✅ |
| 10 | Pre-layout STA | 9 | `phase3/stage3/sta/pre…` | ❓ |
| 11 | DFT insertion | 10 | `phase2/stage2/dft/sca…` | ❓ |
| 12 | Post-DFT optimization | 11 | `phase2/stage2/synth/p…` | ❓ |
| 13 | Equivalence check | 12 | `reports/lec.rpt` | ❓ |

### Stage 3 — Physical Design

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 14 | pre-PnR Yosys gate | 9, 13 | `phase2/stage2/synth/n…` | 🟦 |
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
| 28 | Post-Layout Gate-Level S… | 22 | `phase3/stage3/sim_pos…` | ❓ |
| 29 | Post-Layout SPICE Verifi… | 22, 23 | `phase3/stage3/spice/*…` | ❓ |
| 30 | Physical Verification | 23–29 (7) | `reports/phase3/drc_si…` | ❓ |
| 31 | ECO | 23–30 (8) | `phase3/stage3/eco/eco…` | ❓ |

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
| 32 | Power analysis | 23 | `reports/phase3/power.…` | ❓ |
| 33 | Metal Fill | 31 | `phase3/stage3/pnr/fil…` | ❓ |
| 34 | Tapeout checklist | 30, 31, 32, 33 | `reports/audit/tapeout…` | ❓ |
| 35 | GDSII output | 33, 34 | `phase3/stage4/gds/*.g…` | ✅ |
| 36 | Foundry Handoff | 35 | `phase3/stage4/foundry…` | ❓ |
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
| ✅ PASS | 8 |
| 🟦 VACUOUS-PASS | 1 |
| ⏭️ SKIPPED-CONDITION | 17 |
| ❌ FAIL | 2 |
| ❓ MISSING | 28 |
| **Total** | **56** |

## Waivers (must be human-reviewed before tapeout)

### Step ? — `TAPEOUT-AUTOGEN-LVS`

- **Approver**: `—`    **review_required**: ✅
- **Evidence**: `['reports/orchestrator/phase3_one_shot.json#steps[name=lvs]']`

```
(no reason given — waiver is INVALID)
```

## Resource log

- Canonical step PASS: **8/39** (deferred via waiver: 0, vacuous-pass: 1, manufacturing-skipped: 17)

## SHA-256 Attestation

Independent reviewers can verify any artefact by re-
computing `sha256sum <path>` and comparing against the
table below. Every canonical artefact present on disk
is listed; mismatches or omissions are caught by
`agent_report_sha256_attestation_check.py`.

| Artefact | Path | Size (B) | SHA-256 |
|---|---|---:|---|
| chip GDS | `phase3/stage4/gds/chip_top.gds` | 961,708 | `sha256:9a23e23d61e925f19bd28a05fefe62fa67073289484eab890b84156ac79a2679` |
| synth netlist | `phase2/stage2/synth/netlist.v` | 74,571 | `sha256:3b687d0d171b861b814ad8fd88929907ed29ea542891c9c6c82f080ad9c87e1f` |
| synth netlist | `phase2/stage2/synth/netlist_yosys.v` | 74,571 | `sha256:3b687d0d171b861b814ad8fd88929907ed29ea542891c9c6c82f080ad9c87e1f` |

## Self-attestation

```bash
python3 /home/reyerchu/vibe-ic/.claude/worktrees/land-cascade/vibe-ic-marketplace/plugins/vibe-ic/programs/flow_compliance_check.py \
    /home/reyerchu/vibe-ic/.claude/worktrees/land-cascade/benchmark_phase1/mdio --strict
```

## Chip-specific addendum

_No `reports/chip_specific_summary.md` present. Author it by hand (or via a chip-specific Phase-2a skill) to document IC-specific test interpretations, opcode tables, tuning-target values, etc. This generator deliberately keeps the canonical summary chip-agnostic._

