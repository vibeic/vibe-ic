# Phase 2+3 Final Summary — spm

_Auto-generated chip-AGNOSTIC summary by_ `final_report_generate.py` _at 2026-05-29T08:01:48Z (UTC)._

- **IC**: `(unknown — fill in via L1_DATASHEET.json[ic_name])`
- **Project root**: `/home/reyerchu/vibe-ic/benchmark_clean/spm`

## Verdict

**`Overall: FAIL`**

```
=== Vibe-IC phase1_phase2_phase3 compliance ===
Project: /home/reyerchu/vibe-ic/benchmark_clean/spm
Flow def: /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/0.1.61/flow/phase1_phase2_phase3.yaml
Steps: 56 total (9/39 executed PASS, 0 DEFERRED via waiver)
  PASS=8  FAIL=5  MISSING=25  WAIVED-DEFERRED=0  SKIPPED=17  VACUOUS-PASS=1
```

- PASS=7 — every executed canonical step passed deterministically.
- SKIPPED-CONDITION=17 — gate predicate not yet met (e.g., manufacturing steps awaiting silicon).
- VACUOUS-PASS=1 — gate accepts the present project shape; check whether it should be a real PASS for your flow.
- **FAIL=5** — blocking; do not claim PASS.

Per the SOLE ACCEPTANCE CRITERION: `executed PASS = 7/7, deferred = 0 pending foundry sign-off`. Engineering Phase 2+3 INCOMPLETE — fix FAILs before claiming.

## Stage breakdown

| Stage | Steps | PASS | Other |
|---|---|---:|---|
| Stage 1 (RTL) | 1–6, P0 (7) | 4 / 7 | ❌=3 |
| Stage 2 (Synth/DFT) | 7–13 (7) | 1 / 7 | ❌=1 ❓=5 |
| Stage 3 (PD) | 14–31 (18) | 2 / 18 | 🟦=1 ❓=16 |
| Analog (A1–A9) | A1–A9 (9) | 0 / 9 | ⏭️=9 |
| Mixed-Signal (M1–M4) | M1–M4 (4) | 0 / 4 | ⏭️=4 |
| Stage 4 (Sign-off) | 32–37 (6) | 1 / 6 | ❌=1 ❓=4 |
| Stage 5 (Mfg) | 38–41 (4) | 0 / 4 | ⏭️=4 |

## Output #1 — Hardware verification (generic)

- **Verdict**: `PASS`
- _Source_: `reports/hw_test.json`
- **Bitstream**: `phase2/stage1/fpga/output_files/spm_fpga_bist.sof` (3,216,569 B)
- **Bitstream SHA-256**: `abfb472d8510ac392e05a0e4f1a2878a35fd3c6643c0fca82accd54ee7cda9dd`

## Output #2 — FPGA-verified GDS

- **GDS**: `phase3/stage4/gds/spm.gds` (4,260,752 B)
- **GDS SHA-256**: `59beabf942baa0a64819058f55e0ad54575b51384883e04fed46eeb179bd3fe0`
- **Physical verification**: drc_signoff=`(report missing)`, lvs=`(report missing)`, erc=`(report missing)`

## Output #3 — Test patterns (count summary)

- _No `reports/test_cases.json` found._

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
| PnR DEF (COMPONENTS) | — | _(no DEF found)_ |

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
| 5 | Formal verification | 2 | `phase2/stage1/formal…` | ❌ |
| 6 | FPGA early prototype + v… | 2, 4, 5 | `phase2/stage1/fpga/ou…` | ✅ |

### Stage 2 — Synthesis + DFT

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 7 | Constraint setup | 1 | `phase2/stage2/constra…` | ❌ |
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
| 18 | Spare-cell + ECO-prep in… | 17 | `phase3/stage3/pnr/spa…` | ✅ |
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
| ✅ PASS | 7 |
| 🟦 VACUOUS-PASS | 1 |
| ⏭️ SKIPPED-CONDITION | 17 |
| ❌ FAIL | 5 |
| ❓ MISSING | 26 |
| **Total** | **56** |

## Waivers (must be human-reviewed before tapeout)

_No waivers — every executed step verified deterministically._

## Resource log

- Analog blocks: 2 × 9 stages = 18 per-block step-runs (artefacts present: 0/18)
- Canonical step PASS: **7/39** (deferred via waiver: 0, vacuous-pass: 1, manufacturing-skipped: 17)

## SHA-256 Attestation

Independent reviewers can verify any artefact by re-
computing `sha256sum <path>` and comparing against the
table below. Every canonical artefact present on disk
is listed; mismatches or omissions are caught by
`agent_report_sha256_attestation_check.py`.

| Artefact | Path | Size (B) | SHA-256 |
|---|---|---:|---|
| FPGA SOF | `phase2/stage1/fpga/output_files/spm_fpga_bist.sof` | 3,216,569 | `sha256:abfb472d8510ac392e05a0e4f1a2878a35fd3c6643c0fca82accd54ee7cda9dd` |
| chip GDS | `phase3/stage4/gds/spm.gds` | 4,260,752 | `sha256:59beabf942baa0a64819058f55e0ad54575b51384883e04fed46eeb179bd3fe0` |
| synth netlist | `phase2/stage2/synth/netlist.v` | 61,667 | `sha256:70be730d369a913d97655a16b2cc7942bc1bb5ef2b922e03758807b483c158da` |
| synth netlist | `phase2/stage2/synth/netlist_yosys.v` | 61,667 | `sha256:70be730d369a913d97655a16b2cc7942bc1bb5ef2b922e03758807b483c158da` |
| synth netlist | `phase2/stage2/synth/spm_synth.v` | 30,900 | `sha256:d684cdf4837a08e96bf7e300c68980a5b5790a9e5dc39fa975b9e2fddc8f7ebd` |
| PnR netlist | `phase3/stage3/pnr/spm_pnr.v` | 31,192 | `sha256:8d01caaf620a4f702c43770a1b200bdfa65c01eb2e97d54149f7ea6176d1bb51` |

## Self-attestation

```bash
python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/0.1.61/programs/flow_compliance_check.py \
    /home/reyerchu/vibe-ic/benchmark_clean/spm --strict
```

## Chip-specific addendum

_No `reports/chip_specific_summary.md` present. Author it by hand (or via a chip-specific Phase-2a skill) to document IC-specific test interpretations, opcode tables, tuning-target values, etc. This generator deliberately keeps the canonical summary chip-agnostic._

