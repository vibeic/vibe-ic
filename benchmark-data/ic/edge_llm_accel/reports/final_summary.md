# Phase 2+3 Final Summary — edge_llm_accel

_Auto-generated chip-AGNOSTIC summary by_ `final_report_generate.py` _at 2026-07-19T02:59:25Z (UTC)._

- **IC**: `edge_llm_accel`
- **Project root**: `/home/reyerchu/vibe-ic/benchmark-data/ic/edge_llm_accel`

## Verdict

**`Overall: FAIL`**

_Counts snapshot 2026-07-19T02:59:25Z · audit-digest sha256:5ec2a7141a38 · overall FAIL. A fresh `flow_compliance_check.py --strict` re-run may move these once late artefacts land._

```
=== Vibe-IC phase1_phase2_phase3 compliance ===
Project: /home/reyerchu/vibe-ic/benchmark-data/ic/edge_llm_accel
Flow def: /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml
Steps: 63 total (22/34 executed PASS, 4 DEFERRED via waiver)
  PASS=22  FAIL=8  MISSING=4 (3 blocked-by-upstream of step 13)  WAIVED-DEFERRED=4  SKIPPED=25
```

- PASS=20 (+VACUOUS-PASS=0 → executed PASS=20) — every executed canonical step passed deterministically.
- WAIVED-DEFERRED=4 — deferred via documented waiver (human review required before tapeout).
- SKIPPED-CONDITION=22 — gate predicate not yet met. manufacturing-stage (awaiting silicon)=5; mid-flow (board absent / capability gap / cascade-blocked)=17.
- **FAIL=8** — blocking; do not claim PASS.

Per the SOLE ACCEPTANCE CRITERION: `executed PASS = 20/37, deferred = 4 pending foundry sign-off`. Engineering Phase 2+3 INCOMPLETE — fix FAILs before claiming.

## Stage breakdown

| Stage | Steps | PASS | Other |
|---|---|---:|---|
| Stage 1 (RTL) | 1–6, P0 (7) | 4 / 7 | ⚠️=2 ⏭️=1 |
| Stage 2 (Synth/DFT) | 7–14, DT1, DT2, DT3, FS1 (12) | 4 / 12 | ⏭️=1 ❌=2 ❓=5 |
| Stage 3 (PD) | 15–32 (18) | 9 / 18 | ⏭️=2 ❌=5 ❓=2 |
| Analog (A1–A9) | A1–A9 (9) | 0 / 9 | ⏭️=9 |
| Mixed-Signal (M1–M4) | M1–M4 (4) | 0 / 4 | ⏭️=4 |
| Stage 4 (Sign-off) | 33–39 (7) | 3 / 7 | ⚠️=2 ❌=1 ❓=1 |
| Stage 5 (Mfg) | 40–44 (5) | 0 / 5 | ⏭️=5 |

## Output #1 — Hardware verification (generic)

_No `reports/hw_test.json` or legacy `reports/md905_test.json` found._

## Output #2 — FPGA-verified GDS

- **GDS**: `phase3/stage4/gds/edge_llm_accel.gds` (2,232,410,676 B)
- **GDS SHA-256**: `d16b00de89211321d59cdaeb6b6599ff56b9ab06d871fe09f577f5b97b866f36`
- **Physical verification**: drc_signoff=`(report missing)`, lvs=`?`, erc=`BENIGN-ERC`
- **Auxiliary signoff reports** (3): `reports/phase3/antenna.json`, `reports/phase3/si_crosstalk.json`, `reports/phase3/power.json`

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
| Yosys post-synth | 3104629 | `phase2/stage2/synth/netlist.v (count: yosys.log)` |
| PnR DEF (COMPONENTS) | 1494657 | `phase3/stage3/pnr/routed.def` |

### Top-15 cell-type histogram

| Cell | Count |
|---|---:|
| `\$_NOR_` | 1305211 |
| `\$_NAND_` | 1054894 |
| `\$_NOT_` | 626167 |
| `\$_DFF_PN0_` | 114195 |
| `\$_DFF_P_` | 44 |
| `fakeram45_2048x39` | 20 |
| `\$_DFF_PN1_` | 1 |

## Canonical step input/output (63 entities)

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
| 4 | Simulation | 2 | `phase2/stage1/sim/*.l…` | ⚠️ |
| 5 | Formal verification | 2 | `phase2/stage1/formal…` | ⏭️ |
| 6 | FPGA early prototype + v… | 2, 4, 5 | `phase2/stage1/fpga/ou…` | ⚠️ |

### Stage 2 — Synthesis + DFT

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 7 | Constraint setup | 1 | `phase2/stage2/constra…` | ✅ |
| 8 | SDC validation | 7 | `reports/phase2/sdc_ch…` | ✅ |
| 9 | Synthesis | 2, 3, 8 | `phase2/stage2/synth/n…` | ✅ |
| 10 | Pre-layout STA | 9 | `phase3/stage3/sta/pre…` | ✅ |
| 11 | DFT insertion | 10 | `phase2/stage2/dft/sca…` | ❓ |
| 12 | Post-DFT optimization | 11 | `phase2/stage2/synth/p…` | ⏭️ |
| 13 | Equivalence check | 12 | `reports/lec.rpt` | ❌ |
| 14 | Synthesis handoff gate | 9, 13 | `phase2/stage2/synth/n…` | ❌ |
| DT1 | Transition-delay-fault (… | 11 | — | ? |
| DT2 | Path-delay-fault (at-spe… | DT1 | — | ? |
| DT3 | Small-delay-defect (SDD)… | DT2 | — | ? |
| FS1 | ISO-26262 FMEDA diagnost… | 11 | — | ? |

### Stage 3 — Physical Design

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 15 | Floorplan + PDN | 13, 14, A8 | `phase3/stage3/pnr/flo…` | ❌ |
| 16 | Clock planning | 15 | `phase3/stage3/cts/clo…` | ✅ |
| 17 | Placement | 16 | `phase3/stage3/pnr/pla…` | ✅ |
| 18 | Spare-cell + ECO-prep in… | 17 | `phase3/stage3/pnr/spa…` | ❌ |
| 19 | CTS | 18 | `phase3/stage3/pnr/pos…` | ✅ |
| 20 | Post-CTS hold fixing | 19 | `phase3/stage3/pnr/pos…` | ✅ |
| 21 | Routing | 20 | `phase3/stage3/pnr/rou…` | ✅ |
| 22 | Parasitic Extraction | 21 | `phase3/stage3/extract…` | ✅ |
| 23 | Post-route STA | 22 | `phase3/stage3/sta/pos…` | ✅ |
| 24 | IR Drop | 22 | `reports/phase3/ir_dro…` | ❓ |
| 25 | EM check | 22 | `reports/phase3/em.rpt` | ❓ |
| 26 | Antenna check | 21 | `reports/phase3/antenn…` | ✅ |
| 27 | Signal Integrity | 22 | `reports/phase3/si_cro…` | ✅ |
| 28 | PERC / Reliability sign-… | 21–27 (5) | `reports/phase3/perc_e…` | ❌ |
| 29 | Post-Layout Gate-Level S… | 22 | `phase3/stage3/sim_pos…` | ⏭️ |
| 30 | Post-Layout SPICE Verifi… | 22, 23 | `phase3/stage3/spice/*…` | ⏭️ |
| 31 | Physical Verification | 23–30 (7) | `reports/phase3/drc_si…` | ❌ |
| 32 | ECO | 23–31 (8) | `phase3/stage3/eco/eco…` | ❌ |

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
| 33 | Power analysis | 23 | `reports/phase3/power.…` | ✅ |
| 34 | Metal Fill | 32 | `phase3/stage3/pnr/fil…` | ❓ |
| 35 | DFM screen | 34 | `reports/phase3/dfm_sc…` | ✅ |
| 36 | Tapeout checklist | 31, 32, 33, 34 | `reports/audit/tapeout…` | ⚠️ |
| 37 | GDSII output | 34, 36 | `phase3/stage4/gds/*.g…` | ✅ |
| 38 | Foundry Handoff | 37 | `phase3/stage4/foundry…` | ❌ |
| 39 | FPGA final sign-off | 13 | `phase2/stage1/fpga/fi…` | ⚠️ |

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
| ✅ PASS | 20 |
| ⚠️ WAIVED-DEFERRED | 4 |
| ⏭️ SKIPPED-CONDITION | 22 |
| ❌ FAIL | 8 |
| ❓ MISSING | 9 |
| **Total** | **63** |

## Waivers (must be human-reviewed before tapeout)

### Step 39 — `fpga-board-prototype-capgap-v1.0.18`

- **Approver**: `field-agent-attest (fpga-board cap-gap tier)`    **review_required**: ✅
- **Evidence**: `['reports/phase2/fpga/quartus_map_audit.json']`

```
ENV_UNAVAILABLE (fpga-board-prototype cap-gap): the runner HONESTLY self-reports a deliberate FPGA skip (reports/phase2/fpga/quartus_map_audit.json verdict=SKIP, sof_present=false) — no DE10-class board-pin contract for this IC class and/or no Quartus on host. The on-board .sof (early-prototype AND final sign-off) is DEFERRED to board bring-up (NOT executed-PASS) [ticket=fpga-board-prototype-capgap-v1.0.18, review_required=True, cap:fpga_board_prototype]
```

### Step 6 — `fpga-board-prototype-capgap-v1.0.18`

- **Approver**: `field-agent-attest (fpga-board cap-gap tier)`    **review_required**: ✅
- **Evidence**: `['reports/phase2/fpga/quartus_map_audit.json']`

```
ENV_UNAVAILABLE (fpga-board-prototype cap-gap): the runner HONESTLY self-reports a deliberate FPGA skip (reports/phase2/fpga/quartus_map_audit.json verdict=SKIP, sof_present=false) — no DE10-class board-pin contract for this IC class and/or no Quartus on host. The on-board .sof (early-prototype AND final sign-off) is DEFERRED to board bring-up (NOT executed-PASS) [ticket=fpga-board-prototype-capgap-v1.0.18, review_required=True, cap:fpga_board_prototype]
```

### Step 36 — `ORGANIC-20260613-tapeout-drc-waiver`

- **Approver**: `tapeout-review-pending`    **review_required**: ✅
- **Evidence**: `['reports/phase3/drc_signoff.rpt']`

```
tapeout sign-off reached the evidence threshold but a DRC/LVS slot was credited via a waiver (verdict_tier=PASS_WITH_WAIVERS) — NOT a bare/absolute PASS. Production tapeout review must close the waived slot before mask order (CLAUDE.md rule 11).
```

## Resource log

- Standard-cell count post-synth: **3104629** (from `phase2/stage2/synth/netlist.v`)
- DEF COMPONENTS post-PnR: **1494657**
- Canonical step executed PASS: **20/37** (strict PASS: 20, deferred via waiver: 4, vacuous-pass: 0, manufacturing-skipped: 5, mid-flow-skipped: 17)

## SHA-256 Attestation

Independent reviewers can verify any artefact by re-
computing `sha256sum <path>` and comparing against the
table below. Every canonical artefact present on disk
is listed; mismatches or omissions are caught by
`agent_report_sha256_attestation_check.py`.

| Artefact | Path | Size (B) | SHA-256 |
|---|---|---:|---|
| chip GDS | `phase3/stage4/gds/edge_llm_accel.gds` | 2,232,410,676 | `sha256:d16b00de89211321d59cdaeb6b6599ff56b9ab06d871fe09f577f5b97b866f36` |
| foundry GDS | `phase3/stage4/foundry_handoff/edge_llm_accel.gds` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| synth netlist | `phase2/stage2/synth/_dlatch_map.v` | 170 | `sha256:3b4684a7c0216715e63ac0fd254a160bea24a40bdbe6f18d1c9ce4ef4c5b8c2f` |
| synth netlist | `phase2/stage2/synth/edge_llm_accel_sv2v.v` | 7,491 | `sha256:3e5859c5765b22b224219fe98a339fff6aa56a8d92d9d3f15b3c33d94edcd2ca` |
| synth netlist | `phase2/stage2/synth/edge_llm_accel_synth.v` | 175,556,112 | `sha256:ecd71111cae76e4f22d595b49e3ff111f2244225fd8e7422e3e29a46360ad831` |
| synth netlist | `phase2/stage2/synth/netlist.v` | 357,790,454 | `sha256:93c036a500efbb46344891eea2cf8ca0abe2320271a5e8b61e2a1dec4c946581` |
| synth netlist | `phase2/stage2/synth/netlist_yosys.v` | 357,790,454 | `sha256:93c036a500efbb46344891eea2cf8ca0abe2320271a5e8b61e2a1dec4c946581` |
| PnR netlist | `phase3/stage3/pnr/edge_llm_accel_pnr.v` | 166,254,492 | `sha256:3726eba9377f17ea64d316f52e53938d3d44dae8c754c75ccb6d3ac895baa7a0` |

## Self-attestation

```bash
python3 /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/flow_compliance_check.py \
    /home/reyerchu/vibe-ic/benchmark-data/ic/edge_llm_accel --strict
```

## Chip-specific addendum

_No `reports/chip_specific_summary.md` present. Author it by hand (or via a chip-specific Phase 1 skill) to document IC-specific test interpretations, opcode tables, tuning-target values, etc. This generator deliberately keeps the canonical summary chip-agnostic._

