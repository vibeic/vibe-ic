# Phase 2+3 Final Summary — sgmii

_Auto-generated chip-AGNOSTIC summary by_ `final_report_generate.py` _at 2026-06-01T19:11:00Z (UTC)._

- **IC**: `(unknown — fill in via L1_DATASHEET.json[ic_name])`
- **Project root**: `/home/reyerchu/vibe-ic/benchmark_phase1/sgmii`

## Verdict

**`Overall: FAIL`**

```
=== Vibe-IC phase1_phase2_phase3 compliance ===
Project: /home/reyerchu/vibe-ic/benchmark_phase1/sgmii
Flow def: /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml
Steps: 56 total (22/39 executed PASS, 0 DEFERRED via waiver)
  PASS=21  FAIL=13  MISSING=4  WAIVED-DEFERRED=0  SKIPPED=17  VACUOUS-PASS=1
```

- PASS=20 — every executed canonical step passed deterministically.
- SKIPPED-CONDITION=17 — gate predicate not yet met (e.g., manufacturing steps awaiting silicon).
- VACUOUS-PASS=1 — gate accepts the present project shape; check whether it should be a real PASS for your flow.
- **FAIL=13** — blocking; do not claim PASS.

Per the SOLE ACCEPTANCE CRITERION: `executed PASS = 20/20, deferred = 0 pending foundry sign-off`. Engineering Phase 2+3 INCOMPLETE — fix FAILs before claiming.

## Stage breakdown

| Stage | Steps | PASS | Other |
|---|---|---:|---|
| Stage 1 (RTL) | 1–6, P0 (7) | 3 / 7 | ❌=4 |
| Stage 2 (Synth/DFT) | 7–13 (7) | 2 / 7 | ❌=2 ❓=3 |
| Stage 3 (PD) | 14–31 (18) | 12 / 18 | 🟦=1 ❌=5 ❓=1 |
| Analog (A1–A9) | A1–A9 (9) | 0 / 9 | ⏭️=9 |
| Mixed-Signal (M1–M4) | M1–M4 (4) | 0 / 4 | ⏭️=4 |
| Stage 4 (Sign-off) | 32–37 (6) | 4 / 6 | ❌=2 |
| Stage 5 (Mfg) | 38–41 (4) | 0 / 4 | ⏭️=4 |

## Output #1 — Hardware verification (generic)

_No `reports/hw_test.json` or legacy `reports/md905_test.json` found._

## Output #2 — FPGA-verified GDS

- **GDS**: `phase3/stage4/gds/chip_top.gds` (1,174,284 B)
- **GDS SHA-256**: `8bd856f4aea7fee2007513bd33bf4623b03c6dcfc787fc1d6d64dc0f70e8ff8f`
- **Physical verification**: drc_signoff=`(report missing)`, lvs=`(report missing)`, erc=`REVIEW`
- **Auxiliary signoff reports** (5): `reports/phase3/ir_drop.json`, `reports/phase3/em.json`, `reports/phase3/antenna.json`, `reports/phase3/si_crosstalk.json`, `reports/phase3/power.json`

## Output #3 — Test patterns (count summary)

- _No `reports/test_cases.json` found._

_Per-opcode / per-mode coverage detail belongs in_ `reports/chip_specific_summary.md` _(this section stays chip-agnostic)._

## Output #4 — Analog convergence (tuning loops)

_No `analog/analog_block_list.json` found — pure-digital project, or analog track not run._

## Cell count (synth + PnR)

| Stage | Count | Source |
|---|---:|---|
| Yosys post-synth | 0 | `phase2/stage2/synth/netlist.v` |
| PnR DEF (COMPONENTS) | 3219 | `phase3/stage3/pnr/routed.def` |

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
| 6 | FPGA early prototype + v… | 2, 4, 5 | `phase2/stage1/fpga/ou…` | ❌ |

### Stage 2 — Synthesis + DFT

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 7 | Constraint setup | 1 | `phase2/stage2/constra…` | ❌ |
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
| 18 | Spare-cell + ECO-prep in… | 17 | `phase3/stage3/pnr/spa…` | ❌ |
| 19 | CTS | 18 | `phase3/stage3/pnr/pos…` | ✅ |
| 20 | Post-CTS hold fixing | 19 | `phase3/stage3/pnr/pos…` | ✅ |
| 21 | Routing | 20 | `phase3/stage3/pnr/rou…` | ❌ |
| 22 | Parasitic Extraction | 21 | `phase3/stage3/extract…` | ❌ |
| 23 | Post-route STA | 22 | `phase3/stage3/sta/pos…` | ❌ |
| 24 | IR Drop | 22 | `reports/phase3/ir_dro…` | ✅ |
| 25 | EM check | 22 | `reports/phase3/em.rpt` | ✅ |
| 26 | Antenna check | 21 | `reports/phase3/antenn…` | ✅ |
| 27 | Signal Integrity | 22 | `reports/phase3/si_cro…` | ✅ |
| 28 | Post-Layout Gate-Level S… | 22 | `phase3/stage3/sim_pos…` | ✅ |
| 29 | Post-Layout SPICE Verifi… | 22, 23 | `phase3/stage3/spice/*…` | ❓ |
| 30 | Physical Verification | 23–29 (7) | `reports/phase3/drc_si…` | ❌ |
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
| 33 | Metal Fill | 31 | `phase3/stage3/pnr/fil…` | ❌ |
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
| ❌ FAIL | 13 |
| ❓ MISSING | 5 |
| **Total** | **56** |

## Waivers (must be human-reviewed before tapeout)

### Step ? — `TAPEOUT-LVS-DEVICELEVEL`

- **Approver**: `—`    **review_required**: ✅
- **Evidence**: `['phase2/stage2/synth/chip_top_synth.v', 'phase3/stage3/pnr/chip_top_pnr_logiconly.v', 'reports/orchestrator/phase3_one_shot.json#steps[name=lvs]']`

```
(no reason given — waiver is INVALID)
```

### Step ? — `TAPEOUT-AUTOGEN-DRC-CELLLIB`

- **Approver**: `—`    **review_required**: ✅
- **Evidence**: `['phase3/reports/drc.rpt', 'phase3/stage3/pnr/openroad.log#DRT-0199=0', 'reports/orchestrator/phase3_one_shot.json#steps[name=drc]']`

```
(no reason given — waiver is INVALID)
```

## Resource log

- DEF COMPONENTS post-PnR: **3219**
- Canonical step PASS: **20/39** (deferred via waiver: 0, vacuous-pass: 1, manufacturing-skipped: 17)

## SHA-256 Attestation

Independent reviewers can verify any artefact by re-
computing `sha256sum <path>` and comparing against the
table below. Every canonical artefact present on disk
is listed; mismatches or omissions are caught by
`agent_report_sha256_attestation_check.py`.

| Artefact | Path | Size (B) | SHA-256 |
|---|---|---:|---|
| chip GDS | `phase3/stage4/gds/chip_top.gds` | 1,174,284 | `sha256:8bd856f4aea7fee2007513bd33bf4623b03c6dcfc787fc1d6d64dc0f70e8ff8f` |
| foundry GDS | `phase3/stage4/foundry_handoff/chip_top.gds` | 1,174,284 | `sha256:8bd856f4aea7fee2007513bd33bf4623b03c6dcfc787fc1d6d64dc0f70e8ff8f` |
| foundry GDS | `phase3/stage4/foundry_handoff/scribe_line_layout.gds` | 137 | `sha256:aa06450c7345ae3e71d83f98b09879db39dd45f091515a377557320c565e3122` |
| synth netlist | `phase2/stage2/synth/_dlatch_map.v` | 192 | `sha256:d22ec196b64163ed3f84528bfd444723b1a5bb262d3047801457e324a5da16eb` |
| synth netlist | `phase2/stage2/synth/chip_top_synth.v` | 72,298 | `sha256:84de40ada3ca76fd4520186bd5a628e95eb097fdc22fd34797eafd9b6e163b98` |
| synth netlist | `phase2/stage2/synth/netlist.v` | 126,139 | `sha256:a8218d8984dd9a5516fc33b048edeab2698cc05f028cbf2755e112717fa0a85e` |
| synth netlist | `phase2/stage2/synth/netlist_yosys.v` | 125,935 | `sha256:c74dd92a606b9d4efa176389327176eeba9cb9c43c6a445b346ecb3672e31625` |
| PnR netlist | `phase3/stage3/pnr/chip_top_pnr.v` | 188,038 | `sha256:d3aabea5b3a7a4520d23f3622e358a5f8b5429359959fc2dbd3d49791f2c10d4` |
| PnR netlist | `phase3/stage3/pnr/chip_top_pnr_logiconly.v` | 74,651 | `sha256:f63d30969456b35428b9a21bde6ca5bb317f28ac4892d89d3235d5c4a6d8e59e` |

## Self-attestation

```bash
python3 /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/flow_compliance_check.py \
    /home/reyerchu/vibe-ic/benchmark_phase1/sgmii --strict
```

## Chip-specific addendum

_No `reports/chip_specific_summary.md` present. Author it by hand (or via a chip-specific Phase-2a skill) to document IC-specific test interpretations, opcode tables, tuning-target values, etc. This generator deliberately keeps the canonical summary chip-agnostic._

