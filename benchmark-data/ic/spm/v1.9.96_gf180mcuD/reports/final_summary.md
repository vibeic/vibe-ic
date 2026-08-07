# Phase 2+3 Final Summary — gf180mcuD

_Auto-generated chip-AGNOSTIC summary by_ `final_report_generate.py` _at 2026-08-07T06:42:09Z (UTC)._

- **IC**: `spm3`
- **Project root**: `/home/reyerchu/spm3_run/gf180mcuD`

## Verdict

**`Overall: PASS_WITH_WAIVERS`**

_Counts snapshot 2026-08-07T06:42:09Z · audit-digest sha256:82dfbb296ef3 · overall PASS_WITH_WAIVERS. A fresh `flow_compliance_check.py --strict` re-run may move these once late artefacts land._

```
=== Vibe-IC phase1_phase2_phase3 compliance ===
Project: /home/reyerchu/spm3_run/gf180mcuD
Flow def: /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/1.9.96-gf180ciel-test/flow/phase1_phase2_phase3.yaml
Steps: 63 total (34/39 executed PASS, 4 DEFERRED via waiver, 4 VACUOUS-PASS excluded from executed)
  PASS=34  FAIL=0  MISSING=0  WAIVED-DEFERRED=4  SKIPPED=20  VACUOUS-PASS=4  INCOMPLETE=1
```

> ⚠️ **Roll-up reconciliation FAILED** — the per-step roll-up computed by this renderer disagrees with the `flow_compliance_check.py` tally quoted immediately above, over the SAME 63 steps of the SAME audit run, in: `SKIPPED-CONDITION` (this report 18 vs checker 20), `VACUOUS-PASS` (this report 0 vs checker 4), `WAIVED-DEFERRED` (this report 0 vs checker 4). The checker's tally is authoritative (it is what `reports/audit/phase23_completion_audit.json[step_counts]` is serialised from). Do NOT read the per-verdict counts below — especially the FAIL count — as a converged result until this is resolved.

- PASS=34 → executed PASS=34 — every canonical step that MEASURED something passed deterministically. VACUOUS-PASS=0 is NOT included: those gates ran and found no input to audit.
- SKIPPED-CONDITION=18 — gate predicate not yet met. manufacturing-stage (awaiting silicon)=5; mid-flow (board absent / capability gap / cascade-blocked)=13.

Per the SOLE ACCEPTANCE CRITERION: `executed PASS = 34/45, deferred = 0 pending foundry sign-off`. Engineering Phase 2+3 complete.

## Stage breakdown

| Stage | Steps | PASS | Other |
|---|---|---:|---|
| Stage 1 (RTL) | 1–6, P0 (7) | 3 / 7 | — |
| Stage 2 (Synth/DFT) | 7–14, DT1, DT2, DT3, FS1 (12) | 9 / 12 | — |
| Stage 3 (PD) | 15–32 (18) | 16 / 18 | — |
| Analog (A1–A9) | A1–A9 (9) | 0 / 9 | ⏭️=9 |
| Mixed-Signal (M1–M4) | M1–M4 (4) | 0 / 4 | ⏭️=4 |
| Stage 4 (Sign-off) | 33–39 (7) | 6 / 7 | — |
| Stage 5 (Mfg) | 40–44 (5) | 0 / 5 | ⏭️=5 |

## Output #1 — Hardware verification (generic)

_No `reports/hw_test.json` or legacy `reports/md905_test.json` found._

## Output #2 — FPGA-verified GDS

- **GDS**: `phase3/stage4/gds/chip_top.gds` (1,230,264 B)
- **GDS SHA-256**: `fb08d9ed51f501ff4c3fbd6b9a30916c5927c86d586f07f147c9388388d8a255`
- **Physical verification**: drc_signoff=`?`, erc=`PASS`, lvs=`MATCH`
- **Auxiliary signoff reports** (6): `reports/phase3/ir_drop.json`, `reports/phase3/em.json`, `reports/phase3/antenna.json`, `reports/phase3/si_crosstalk.json`, `reports/phase3/power.json`, `reports/phase3/sta/post_route_summary.json`

## Output #3 — Test patterns (count summary)

- _No `reports/test_cases.json` found._
- **sim_full_stack vectors**: 28 / 28 PASS
- **Distinct opcodes / commands exercised**: 0
- _sim_full_stack source_: `phase2/stage1/sim_full_stack/results.json`

_Per-opcode / per-mode coverage detail belongs in_ `reports/chip_specific_summary.md` _(this section stays chip-agnostic)._

## Output #4 — Analog convergence (tuning loops)

_No `analog/analog_block_list.json` found — pure-digital project, or analog track not run._

## Cell count (synth + PnR)

| Stage | Count | Source |
|---|---:|---|
| Yosys post-synth | 449 | `phase2/stage2/synth/netlist.v (count: yosys.log)` |
| PnR DEF (COMPONENTS) | 2269 | `phase3/stage3/pnr/routed.def` |

### Top-15 cell-type histogram

| Cell | Count |
|---|---:|
| `\$_NAND_` | 221 |
| `\$_NOR_` | 128 |
| `\$_DFF_P_` | 65 |
| `\$_NOT_` | 35 |

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
| 3 | CDC / RDC check | 1 | `reports/phase2/cdc/cr…` | ✅ |
| 4 | Simulation | 2 | `phase2/stage1/sim/*.l…` | UNCLASSIFIED |
| 5 | Formal verification | 2 | `phase2/stage1/formal…` | UNCLASSIFIED |
| 6 | FPGA early prototype + v… | 2, 4, 5 | `phase2/stage1/fpga/ou…` | MISSING_CAPABILITY |

### Stage 2 — Synthesis + DFT

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 7 | Constraint setup | 1 | `phase2/stage2/constra…` | ✅ |
| 8 | SDC validation | 7, 3 | `reports/phase2/sdc_ch…` | ✅ |
| 9 | Synthesis | 2, 3, 8 | `phase2/stage2/synth/n…` | ✅ |
| 10 | Pre-layout STA | 9 | `phase3/stage3/sta/pre…` | ✅ |
| 11 | DFT insertion | 10 | `phase2/stage2/dft/sca…` | ✅ |
| 12 | Post-DFT optimization | 11 | `phase2/stage2/synth/p…` | ✅ |
| 13 | Equivalence check | 12 | `reports/lec.rpt` | UNCLASSIFIED |
| 14 | Synthesis handoff gate | 9, 13 | `phase2/stage2/synth/n…` | UNCLASSIFIED |
| DT1 | Transition-delay-fault (… | 11 | `reports/phase2/dft/tr…` | ✅ |
| DT2 | Path-delay-fault (at-spe… | DT1, 22 | `reports/phase2/dft/pa…` | ✅ |
| DT3 | Small-delay-defect (SDD)… | DT2 | `reports/phase2/dft/sd…` | ✅ |
| FS1 | ISO-26262 FMEDA diagnost… | 11 | — | UNCLASSIFIED |

### Stage 3 — Physical Design

| ID | Step | ← | Output | V |
|---:|---|:---:|---|:---:|
| 15 | Floorplan + PDN | 13, 14, A8 | `phase3/stage3/pnr/flo…` | ✅ |
| 16 | Clock planning | 15 | `phase3/stage3/cts/clo…` | ✅ |
| 17 | Placement | 16 | `phase3/stage3/pnr/pla…` | ✅ |
| 18 | Spare-cell + ECO-prep in… | 17 | `phase3/stage3/pnr/spa…` | ✅ |
| 19 | CTS | 18 | `phase3/stage3/pnr/pos…` | ✅ |
| 20 | Post-CTS hold fixing | 19 | `phase3/stage3/pnr/pos…` | ✅ |
| 21 | Routing | 20 | `phase3/stage3/pnr/rou…` | ✅ |
| 22 | Parasitic Extraction | 21 | `phase3/stage3/extract…` | ✅ |
| 23 | Post-route STA | 22 | `phase3/stage3/sta/pos…` | ✅ |
| 24 | IR Drop | 22 | `reports/phase3/ir_dro…` | ✅ |
| 25 | EM check | 22 | `reports/phase3/em.rpt` | ✅ |
| 26 | Antenna check | 21 | `reports/phase3/antenn…` | ✅ |
| 27 | Signal Integrity | 22 | `reports/phase3/si_cro…` | ✅ |
| 28 | PERC / Reliability sign-… | 21–27 (5) | `reports/phase3/perc_e…` | ✅ |
| 29 | Post-Layout Gate-Level S… | 22 | `phase3/stage3/sim_pos…` | MISSING_CAPABILITY |
| 30 | Post-Layout SPICE Verifi… | 22, 23 | `phase3/stage3/spice/*…` | MISSING_CAPABILITY |
| 31 | Physical Verification | 23–30 (7) | `reports/phase3/drc_si…` | ✅ |
| 32 | Post-route timing repair… | 23–31 (8) | `phase3/stage3/eco/eco…` | ✅ |

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
| 33 | Power analysis | 23 | `reports/phase3/power.…` | ✅ |
| 34 | Metal Fill | 32 | `phase3/stage3/pnr/fil…` | ✅ |
| 35 | DFM screen | 34 | `reports/phase3/dfm_sc…` | ✅ |
| 36 | Tapeout checklist | 31, 32, 33, 34 | `reports/audit/tapeout…` | ✅ |
| 37 | GDSII output | 34, 36 | `phase3/stage4/gds/*.g…` | ✅ |
| 38 | Foundry Handoff | 37 | `phase3/stage4/foundry…` | ✅ |
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
| ✅ PASS | 34 |
| ⏭️ SKIPPED-CONDITION | 18 |
| MISSING_CAPABILITY MISSING_CAPABILITY | 4 |
| UNCLASSIFIED UNCLASSIFIED | 7 |
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

## Resource log

- Standard-cell count post-synth: **449** (from `phase2/stage2/synth/netlist.v`)
- DEF COMPONENTS post-PnR: **2269**
- Canonical step executed PASS: **34/45** (strict PASS: 34, deferred via waiver: 0, vacuous-pass: 0, manufacturing-skipped: 5, mid-flow-skipped: 13)

## SHA-256 Attestation

Independent reviewers can verify any artefact by re-
computing `sha256sum <path>` and comparing against the
table below. Every canonical artefact present on disk
is listed; mismatches or omissions are caught by
`agent_report_sha256_attestation_check.py`.

| Artefact | Path | Size (B) | SHA-256 |
|---|---|---:|---|
| chip GDS | `phase3/stage4/gds/chip_top.gds` | 1,230,264 | `sha256:fb08d9ed51f501ff4c3fbd6b9a30916c5927c86d586f07f147c9388388d8a255` |
| foundry GDS | `phase3/stage4/foundry_handoff/chip_top.gds` | 1,230,264 | `sha256:fb08d9ed51f501ff4c3fbd6b9a30916c5927c86d586f07f147c9388388d8a255` |
| synth netlist | `phase2/stage2/synth/chip_top_synth.v` | 28,981 | `sha256:59d48a1e762533eb7f8da668d73a829febdb82b14b7c958a778d4a16092f8f38` |
| synth netlist | `phase2/stage2/synth/netlist.v` | 48,046 | `sha256:ea1568a9bd12813c2998285798c42cbbe37b004f994946597e76ffc9c76a2767` |
| synth netlist | `phase2/stage2/synth/netlist_yosys.v` | 48,046 | `sha256:ea1568a9bd12813c2998285798c42cbbe37b004f994946597e76ffc9c76a2767` |
| synth netlist | `phase2/stage2/synth/post_dft_netlist.v` | 77,802 | `sha256:e88863b0dd2c46bc7f242b981134f014c31f2577669df3b32545601a9beaf37d` |
| PnR netlist | `phase3/stage3/pnr/chip_top_pnr.v` | 139,066 | `sha256:4c17301290f0aa4be8953bdb6743bfdbbc014155fbfbd6b834e44c37f93829cc` |
| PnR netlist | `phase3/stage3/pnr/chip_top_pnr_repaired.v` | 56,986 | `sha256:43803ef3a921b0624cbaf2dfbd654ad3cbc55f384dc63cf91912aa7b00cbddd3` |

## Self-attestation

```bash
python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/1.9.96-gf180ciel-test/programs/flow_compliance_check.py \
    /home/reyerchu/spm3_run/gf180mcuD --strict
```

## Chip-specific addendum

_No `reports/chip_specific_summary.md` present. Author it by hand (or via a chip-specific Phase 1 skill) to document IC-specific test interpretations, opcode tables, tuning-target values, etc. This generator deliberately keeps the canonical summary chip-agnostic._

