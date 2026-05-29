# Phase 2+3 Final Summary — sha256

_Auto-generated chip-AGNOSTIC summary by_ `final_report_generate.py` _at 2026-05-29T07:58:24Z (UTC)._

- **IC**: `(unknown — fill in via L1_DATASHEET.json[ic_name])`
- **Project root**: `/home/reyerchu/vibe-ic/benchmark_clean/sha256`

## Verdict

**`Overall: UNKNOWN`**

```
(audit failed: Command '['/usr/bin/python3', '/home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/0.1.61/programs/flow_compliance_check.py', '/home/reyerchu/vibe-ic/benchmark_clean/sha256', '--strict']' timed out after 180 seconds)
```

- PASS=0 — every executed canonical step passed deterministically.

Per the SOLE ACCEPTANCE CRITERION: `executed PASS = 0/0, deferred = 0 pending foundry sign-off`. Engineering Phase 2+3 INCOMPLETE — fix FAILs before claiming.

## Stage breakdown

| Stage | Steps | PASS | Other |
|---|---|---:|---|
| Stage 1 (RTL) | 1–6, P0 (7) | 0 / 7 | ❓=7 |
| Stage 2 (Synth/DFT) | 7–13 (7) | 0 / 7 | ❓=7 |
| Stage 3 (PD) | 14–31 (18) | 0 / 18 | ❓=18 |
| Analog (A1–A9) | A1–A9 (9) | 0 / 9 | ❓=9 |
| Mixed-Signal (M1–M4) | M1–M4 (4) | 0 / 4 | ❓=4 |
| Stage 4 (Sign-off) | 32–37 (6) | 0 / 6 | ❓=6 |
| Stage 5 (Mfg) | 38–41 (4) | 0 / 4 | ❓=4 |

## Output #1 — Hardware verification (generic)

- **Verdict**: `PASS`
- _Source_: `reports/hw_test.json`
- **Bitstream**: `phase2/stage1/fpga/output_files/sha256_bist_top.sof` (3,216,575 B)
- **Bitstream SHA-256**: `0136e93a1ecb5a60aaec2e19ce2098f2263bc0e30cbbdf80602a0f0c02c69a28`

## Output #2 — FPGA-verified GDS

- **GDS**: `phase3/stage4/gds/sha256.gds` (10,630,452 B)
- **GDS SHA-256**: `78c959e8076f006664f804d62fd48e4b05cd727369aafba22439aaf9ad6ed68e`
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
| Yosys post-synth | 0 | `phase2/stage2/synth/sha256_synth.v` |
| PnR DEF (COMPONENTS) | 12351 | `phase3/stage3/pnr/routed.def` |

## Canonical step input/output (56 entities)

_Per_ `flow/phase1_phase2_phase3.yaml` _v2._

### P0 — Structural-RTL umbrella (chip-agnostic checkers)

| ID | Coverage | V |
|---|---|:---:|
| **P0** | CDC/RDC + CRC oracle + L9-conformance + protocol audits | ? |

### Stage 1 — RTL generation & verification

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 1 | Spec-to-RTL | — | `phase2/stage1/rtl/*.sv` | ? |
| 2 | Lint | 1 | `reports/phase2/lint/r…` | ? |
| 3 | CDC / RDC check | 1 | `reports/phase2/cdc/cr…` | ? |
| 4 | Simulation | 2 | `phase2/stage1/sim/*.l…` | ? |
| 5 | Formal verification | 2 | `phase2/stage1/formal…` | ? |
| 6 | FPGA early prototype + v… | 2, 4, 5 | `phase2/stage1/fpga/ou…` | ? |

### Stage 2 — Synthesis + DFT

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 7 | Constraint setup | 1 | `phase2/stage2/constra…` | ? |
| 8 | SDC validation | 7 | `reports/phase2/sdc_ch…` | ? |
| 9 | Synthesis | 2, 3, 8 | `phase2/stage2/synth/n…` | ? |
| 10 | Pre-layout STA | 9 | `phase3/stage3/sta/pre…` | ? |
| 11 | DFT insertion | 10 | `phase2/stage2/dft/sca…` | ? |
| 12 | Post-DFT optimization | 11 | `phase2/stage2/synth/p…` | ? |
| 13 | Equivalence check | 12 | `reports/lec.rpt` | ? |

### Stage 3 — Physical Design

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 14 | pre-PnR Yosys gate | 9, 13 | `phase2/stage2/synth/n…` | ? |
| 15 | Floorplan + PDN | 13, 14, A8 | `phase3/stage3/pnr/flo…` | ? |
| 16 | Clock planning | 15 | `phase3/stage3/cts/clo…` | ? |
| 17 | Placement | 16 | `phase3/stage3/pnr/pla…` | ? |
| 18 | Spare-cell + ECO-prep in… | 17 | `phase3/stage3/pnr/spa…` | ? |
| 19 | CTS | 18 | `phase3/stage3/pnr/pos…` | ? |
| 20 | Post-CTS hold fixing | 19 | `phase3/stage3/pnr/pos…` | ? |
| 21 | Routing | 20 | `phase3/stage3/pnr/rou…` | ? |
| 22 | Parasitic Extraction | 21 | `phase3/stage3/extract…` | ? |
| 23 | Post-route STA | 22 | `phase3/stage3/sta/pos…` | ? |
| 24 | IR Drop | 22 | `reports/phase3/ir_dro…` | ? |
| 25 | EM check | 22 | `reports/phase3/em.rpt` | ? |
| 26 | Antenna check | 21 | `reports/phase3/antenn…` | ? |
| 27 | Signal Integrity | 22 | `reports/phase3/si_cro…` | ? |
| 28 | Post-Layout Gate-Level S… | 22 | `phase3/stage3/sim_pos…` | ? |
| 29 | Post-Layout SPICE Verifi… | 22, 23 | `phase3/stage3/spice/*…` | ? |
| 30 | Physical Verification | 23–29 (7) | `reports/phase3/drc_si…` | ? |
| 31 | ECO | 23–30 (8) | `phase3/stage3/eco/eco…` | ? |

### Analog Track A1-A9

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| A1 | Analog Spec Extraction | — | `phase1/analog/*/spec.…` | ? |
| A2 | Analog Topology Selection | A1 | `phase2/analog/*/topol…` | ? |
| A3 | Analog Netlist Generation | A2 | `phase2/analog/*/*.sp` | ? |
| A4 | Analog Corner Sweep | A3 | `phase2/analog/*/corne…` | ? |
| A5 | Analog Layout | A4 | `phase3/analog/*/layou…` | ? |
| A6 | Analog Physical Verifica… | A5 | `phase3/analog/*/drc_c…` | ? |
| A7 | Post-Layout Resimulation | A6 | `phase3/analog/*/pre_v…` | ? |
| A8 | Hardmacro Generation | A7 | `phase3/analog/hardmac…` | ? |
| A9 | Co-Simulation / HW Verif… | A8 | `phase3/mixed_signal/c…` | ? |

### Mixed-Signal M1-M4

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| M1 | Mixed-Signal Top-Level I… | A8, 15 | `phase3/mixed_signal/t…` | ? |
| M2 | Mixed-Signal Power Domai… | M1 | `reports/analog/mixed_…` | ? |
| M3 | Mixed-Signal Verification | M2 | `phase3/mixed_signal/c…` | ? |
| M4 | Mixed-Signal Sign-Off | M3 | `reports/analog/mixed_…` | ? |

### Stage 4 — Sign-off

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 32 | Power analysis | 23 | `reports/phase3/power.…` | ? |
| 33 | Metal Fill | 31 | `phase3/stage3/pnr/fil…` | ? |
| 34 | Tapeout checklist | 30, 31, 32, 33 | `reports/audit/tapeout…` | ? |
| 35 | GDSII output | 33, 34 | `phase3/stage4/gds/*.g…` | ? |
| 36 | Foundry Handoff | 35 | `phase3/stage4/foundry…` | ? |
| 37 | FPGA final sign-off | 13 | `phase2/stage1/fpga/fi…` | ? |

### Stage 5 — Manufacturing (silicon-dependent)

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 38 | Fabrication | 36 | `phase3/stage5_manufac…` | ? |
| 39 | Wafer Sort / Probe Test | 38 | `phase3/stage5_manufac…` | ? |
| 40 | Packaging | 39 | `phase3/stage5_manufac…` | ? |
| 41 | Final Test | 40 | `phase3/stage5_manufac…` | ? |

### Verdict roll-up

| Verdict | Count |
|---|---:|
| ❓ MISSING | 56 |
| **Total** | **56** |

## Waivers (must be human-reviewed before tapeout)

_No waivers — every executed step verified deterministically._

## Resource log

- DEF COMPONENTS post-PnR: **12351**
- Analog blocks: 2 × 9 stages = 18 per-block step-runs (artefacts present: 0/18)
- Canonical step PASS: **0/56** (deferred via waiver: 0, vacuous-pass: 0, manufacturing-skipped: 0)

## SHA-256 Attestation

Independent reviewers can verify any artefact by re-
computing `sha256sum <path>` and comparing against the
table below. Every canonical artefact present on disk
is listed; mismatches or omissions are caught by
`agent_report_sha256_attestation_check.py`.

| Artefact | Path | Size (B) | SHA-256 |
|---|---|---:|---|
| FPGA SOF | `phase2/stage1/fpga/output_files/sha256_bist_top.sof` | 3,216,575 | `sha256:0136e93a1ecb5a60aaec2e19ce2098f2263bc0e30cbbdf80602a0f0c02c69a28` |
| chip GDS | `phase3/stage4/gds/sha256.gds` | 10,630,452 | `sha256:78c959e8076f006664f804d62fd48e4b05cd727369aafba22439aaf9ad6ed68e` |
| chip GDS | `phase3/stage4/gds/sha256_magic.gds` | 25,967,254 | `sha256:1e982971e8f9be78acb9e5116d0e1e4eb6b8ab38ea32680262d4550cd9c03b23` |
| synth netlist | `phase2/stage2/synth/sha256_synth.v` | 1,084,028 | `sha256:77a2f8cf286d279137f8a56760f18913f1bc2b11f1ad57dc8b2633ce9005f6ec` |
| PnR netlist | `phase3/stage3/pnr/sha256_pnr.v` | 1,384,241 | `sha256:8d58a39e0e5965a50a0ae55414260983b9a97ca070a9cc5f7da1e8af3ea0d41f` |

## Self-attestation

```bash
python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/0.1.61/programs/flow_compliance_check.py \
    /home/reyerchu/vibe-ic/benchmark_clean/sha256 --strict
```

## Chip-specific addendum

_No `reports/chip_specific_summary.md` present. Author it by hand (or via a chip-specific Phase-2a skill) to document IC-specific test interpretations, opcode tables, tuning-target values, etc. This generator deliberately keeps the canonical summary chip-agnostic._

