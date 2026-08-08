# Phase 2+3 Final Summary — clean_run_v1.10.2_sky130A_20260808

_Auto-generated chip-AGNOSTIC summary by_ `final_report_generate.py` _at 2026-08-08T15:07:58Z (UTC)._

- **IC**: `opentitan_aes`
- **Project root**: `/home/reyerchu/_ot_aes_run/clean_run_v1.10.2_sky130A_20260808`

## Verdict

**`Overall: FAIL`**

_Counts snapshot 2026-08-08T15:07:58Z · audit-digest sha256:1c0a02f592e0 · overall FAIL. A fresh `flow_compliance_check.py --strict` re-run may move these once late artefacts land._

```
=== Vibe-IC phase1_phase2_phase3 compliance ===
Project: /home/reyerchu/_ot_aes_run/clean_run_v1.10.2_sky130A_20260808
Flow def: /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/1.10.2/flow/phase1_phase2_phase3.yaml
Steps: 63 total (2/38 executed PASS, 4 DEFERRED via waiver, 2 VACUOUS-PASS excluded from executed)
  PASS=2  FAIL=0  MISSING=29 (24 ordered behind waived step 13, which declares no artefact they read — MISSING, not deferred)  WAIVED-DEFERRED=4  SKIPPED=23  VACUOUS-PASS=2  PASS-VOIDED=2  INCOMPLETE=1
```

> ⚠️ **Roll-up reconciliation FAILED** — the per-step roll-up computed by this renderer disagrees with the `flow_compliance_check.py` tally quoted immediately above, over the SAME 63 steps of the SAME audit run, in: `MISSING` (this report 0 vs checker 29), `SKIPPED-CONDITION` (this report 21 vs checker 23), `VACUOUS-PASS` (this report 0 vs checker 2), `WAIVED-DEFERRED` (this report 0 vs checker 4). The checker's tally is authoritative (it is what `reports/audit/phase23_completion_audit.json[step_counts]` is serialised from). Do NOT read the per-verdict counts below — especially the FAIL count — as a converged result until this is resolved.

- PASS=2 → executed PASS=2 — every canonical step that MEASURED something passed deterministically. VACUOUS-PASS=0 is NOT included: those gates ran and found no input to audit.
- SKIPPED-CONDITION=21 — gate predicate not yet met. manufacturing-stage (awaiting silicon)=5; mid-flow (board absent / capability gap / cascade-blocked)=16.

Per the SOLE ACCEPTANCE CRITERION: `executed PASS = 2/42, deferred = 0 pending foundry sign-off`. Engineering Phase 2+3 INCOMPLETE — fix FAILs before claiming.

## Stage breakdown

| Stage | Steps | PASS | Other |
|---|---|---:|---|
| Stage 1 (RTL) | 1–6, P0 (7) | 2 / 7 | ⏭️=1 |
| Stage 2 (Synth/DFT) | 7–14, DT1, DT2, DT3, FS1 (12) | 0 / 12 | ⏭️=2 |
| Stage 3 (PD) | 15–32 (18) | 0 / 18 | — |
| Analog (A1–A9) | A1–A9 (9) | 0 / 9 | ⏭️=9 |
| Mixed-Signal (M1–M4) | M1–M4 (4) | 0 / 4 | ⏭️=4 |
| Stage 4 (Sign-off) | 33–39 (7) | 0 / 7 | — |
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
| Yosys post-synth | 94966 | `phase2/stage2/synth/netlist.v (count: yosys.log)` |
| PnR DEF (COMPONENTS) | — | _(no DEF found)_ |

### Top-15 cell-type histogram

| Cell | Count |
|---|---:|
| `\$_NAND_` | 45325 |
| `\$_NOR_` | 39928 |
| `\$_NOT_` | 6846 |
| `\$_DFF_PN0_` | 2768 |
| `\$_DFF_PN1_` | 99 |

## Canonical step input/output (63 entities)

_Per_ `flow/phase1_phase2_phase3.yaml` _v2._

### P0 — Structural-RTL umbrella (chip-agnostic checkers)

| ID | Coverage | V |
|---|---|:---:|
| **P0** | CDC/RDC + CRC oracle + L9-conformance + protocol audits | UNCLASSIFIED |

### Stage 1 — RTL generation & verification

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 1 | Spec-to-RTL | D1 | `phase2/stage1/rtl/*.sv` | ✅ |
| 2 | Lint | 1 | `reports/phase2/lint/r…` | ✅ |
| 3 | CDC / RDC check | 1 | `reports/phase2/cdc/cr…` | ⏭️ |
| 4 | Simulation | 2 | `phase2/stage1/sim/*.l…` | UNCLASSIFIED |
| 5 | Formal verification | 2 | `phase2/stage1/formal…` | MISSING_CAPABILITY |
| 6 | FPGA early prototype + v… | 2, 4, 5 | `phase2/stage1/fpga/ou…` | MISSING_CAPABILITY |

### Stage 2 — Synthesis + DFT

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 7 | Constraint setup | 1 | `phase2/stage2/constra…` | UNCLASSIFIED |
| 8 | SDC validation | 7, 3 | `reports/phase2/sdc_ch…` | UNCLASSIFIED |
| 9 | Synthesis | 2, 3, 8 | `phase2/stage2/synth/n…` | UNCLASSIFIED |
| 10 | Pre-layout STA | 9 | `phase3/stage3/sta/pre…` | UNCLASSIFIED |
| 11 | DFT insertion | 10 | `phase2/stage2/dft/sca…` | UNCLASSIFIED |
| 12 | Post-DFT optimization | 11 | `phase2/stage2/synth/p…` | MISSING_CAPABILITY |
| 13 | Equivalence check | 12 | `reports/lec.rpt` | UNCLASSIFIED |
| 14 | Synthesis handoff gate | 9, 13 | `phase2/stage2/synth/n…` | UNCLASSIFIED |
| DT1 | Transition-delay-fault (… | 11 | `reports/phase2/dft/tr…` | UNCLASSIFIED |
| DT2 | Path-delay-fault (at-spe… | DT1, 22 | `reports/phase2/dft/pa…` | ⏭️ |
| DT3 | Small-delay-defect (SDD)… | DT2 | `reports/phase2/dft/sd…` | ⏭️ |
| FS1 | ISO-26262 FMEDA diagnost… | 11 | — | UNCLASSIFIED |

### Stage 3 — Physical Design

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 15 | Floorplan + PDN | 13, 14, A8 | `phase3/stage3/pnr/flo…` | UNCLASSIFIED |
| 16 | Clock planning | 15 | `phase3/stage3/cts/clo…` | UNCLASSIFIED |
| 17 | Placement | 16 | `phase3/stage3/pnr/pla…` | UNCLASSIFIED |
| 18 | Spare-cell + ECO-prep in… | 17 | `phase3/stage3/pnr/spa…` | UNCLASSIFIED |
| 19 | CTS | 18 | `phase3/stage3/pnr/pos…` | UNCLASSIFIED |
| 20 | Post-CTS hold fixing | 19 | `phase3/stage3/pnr/pos…` | UNCLASSIFIED |
| 21 | Routing | 20 | `phase3/stage3/pnr/rou…` | UNCLASSIFIED |
| 22 | Parasitic Extraction | 21 | `phase3/stage3/extract…` | UNCLASSIFIED |
| 23 | Post-route STA | 22 | `phase3/stage3/sta/pos…` | UNCLASSIFIED |
| 24 | IR Drop | 22 | `reports/phase3/ir_dro…` | UNCLASSIFIED |
| 25 | EM check | 22 | `reports/phase3/em.rpt` | UNCLASSIFIED |
| 26 | Antenna check | 21 | `reports/phase3/antenn…` | UNCLASSIFIED |
| 27 | Signal Integrity | 22 | `reports/phase3/si_cro…` | UNCLASSIFIED |
| 28 | PERC / Reliability sign-… | 21–27 (5) | `reports/phase3/perc_e…` | UNCLASSIFIED |
| 29 | Post-Layout Gate-Level S… | 22 | `phase3/stage3/sim_pos…` | UNCLASSIFIED |
| 30 | Post-Layout SPICE Verifi… | 22, 23 | `phase3/stage3/spice/*…` | UNCLASSIFIED |
| 31 | Physical Verification | 23–30 (7) | `reports/phase3/drc_si…` | UNCLASSIFIED |
| 32 | Post-route timing repair… | 23–31 (8) | `phase3/stage3/eco/eco…` | UNCLASSIFIED |

### Analog Track A1-A9

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| A1 | Analog Spec Extraction | — | `phase3/analog/*/spec.…` | ⏭️ |
| A2 | Analog Topology Selection | A1 | `phase3/analog/*/topol…` | ⏭️ |
| A3 | Analog Netlist Generation | A2 | `phase3/analog/*/*.sp` | ⏭️ |
| A4 | Analog Corner Sweep | A3 | `phase3/analog/*/corne…` | ⏭️ |
| A5 | Analog Layout | A4 | `phase3/analog/*/layou…` | ⏭️ |
| A6 | Analog Physical Verifica… | A5 | `phase3/analog/*/drc_c…` | ⏭️ |
| A7 | Post-Layout Resimulation | A6 | `phase3/analog/*/pre_v…` | ⏭️ |
| A8 | Hardmacro Generation | A7 | `phase3/analog/hardmac…` | ⏭️ |
| A9 | Co-Simulation | A8 | `phase3/mixed_signal/c…` | ⏭️ |

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
| 33 | Power analysis | 23 | `reports/phase3/power.…` | UNCLASSIFIED |
| 34 | Metal Fill | 32 | `phase3/stage3/pnr/fil…` | UNCLASSIFIED |
| 35 | DFM screen | 34 | `reports/phase3/dfm_sc…` | UNCLASSIFIED |
| 36 | Tapeout checklist | 31, 32, 33, 34 | `reports/audit/tapeout…` | UNCLASSIFIED |
| 37 | GDSII output | 34, 36 | `phase3/stage4/gds/*.g…` | UNCLASSIFIED |
| 38 | Foundry Handoff | 37 | `phase3/stage4/foundry…` | UNCLASSIFIED |
| 39 | FPGA final sign-off | 6, 13 | `phase2/stage1/fpga/fi…` | MISSING_CAPABILITY |

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
| ✅ PASS | 2 |
| ⏭️ SKIPPED-CONDITION | 21 |
| MISSING_CAPABILITY MISSING_CAPABILITY | 4 |
| UNCLASSIFIED UNCLASSIFIED | 36 |
| **Total** | **63** |

## Waivers (must be human-reviewed before tapeout)

_No waivers — every executed step verified deterministically._

## Resource log

- Standard-cell count post-synth: **94966** (from `phase2/stage2/synth/netlist.v`)
- Canonical step executed PASS: **2/42** (strict PASS: 2, deferred via waiver: 0, vacuous-pass: 0, manufacturing-skipped: 5, mid-flow-skipped: 16)

## SHA-256 Attestation

Independent reviewers can verify any artefact by re-
computing `sha256sum <path>` and comparing against the
table below. Every canonical artefact present on disk
is listed; mismatches or omissions are caught by
`agent_report_sha256_attestation_check.py`.

| Artefact | Path | Size (B) | SHA-256 |
|---|---|---:|---|
| synth netlist | `phase2/stage2/synth/chip_top_sv2v.v` | 592,797 | `sha256:9c46b877ebafce6a78142e60159720602349b7b82be6aa3fe30cbe4c56d085a6` |
| synth netlist | `phase2/stage2/synth/netlist.v` | 11,870,289 | `sha256:84edf539acf7035f673fd7f2f606a2879ab92392f996080b21957e65afa514ff` |
| synth netlist | `phase2/stage2/synth/netlist_yosys.v` | 11,870,289 | `sha256:84edf539acf7035f673fd7f2f606a2879ab92392f996080b21957e65afa514ff` |

## Self-attestation

```bash
python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/1.10.2/programs/flow_compliance_check.py \
    /home/reyerchu/_ot_aes_run/clean_run_v1.10.2_sky130A_20260808 --strict
```

## Chip-specific addendum

_No `reports/chip_specific_summary.md` present. Author it by hand (or via a chip-specific Phase 1 skill) to document IC-specific test interpretations, opcode tables, tuning-target values, etc. This generator deliberately keeps the canonical summary chip-agnostic._

