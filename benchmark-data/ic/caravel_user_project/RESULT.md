# RESULT — caravel_user_project (7th benchmark IC), Round 11 (convergence-confirmation)

Clean-room close-loop. Plugin **v1.0.60** (public tree, PUSHED), **#698 fixed**
(Step-28 PERC consumer maps #696 `BENIGN-ERC` float verdict to non-blocking REVIEW;
was falling through to `else→FAIL`).

- Runner: `/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/vibe_ic_one_shot_runner.py` (PUBLIC TREE, v1.0.60)
- Run dir: `_bench7_caravel_v1034_cleanroom/caravel_r11` (clean-room: input/ ONLY)
- PDK sky130A, ic=caravel_user_project, top=user_project_wrapper, die 2920x3520
- Shape A/D. Blind: no reference GDS / spm_pilot / host-scorer.
- Round-10 baseline: Overall FAIL, 28/31 executed PASS, 3 DEFERRED, 3 FAIL
  (P0 phase1-depth | Step-28 PERC [the #698 gap] | Step-38 foundry-handoff).
- Round-10 prediction: #698 should move Step-28 PERC FAIL→PASS/REVIEW;
  expected residual = {P0 phase1-depth, Step-38 foundry-handoff} + cap-gaps.

## Pre-run code confirmation of #698 (public tree v1.0.60)
- `phase3_one_shot_runner._emit_perc_equivalent._auto()` (≈ line 10167):
  `result = "PASS" if verdict=="PASS" else ("REVIEW" if verdict in ("REVIEW","BENIGN-ERC") else "INCOMPLETE" if verdict=="MEASURED" else "FAIL")`.
  → `BENIGN-ERC` now maps to non-blocking `REVIEW` (open-item, not silent PASS).
- §4.05 no-leak (by code path): only the exact token `BENIGN-ERC` (the #696 benign
  class) maps to REVIEW; a genuine functional float emits `ERC_DIRTY`/non-benign
  token → falls to `else → FAIL`. Real float still hard-FAILs PERC.

<!-- APPEND after each major Phase-3 step -->

## Run log (re-invoke with recovered RTL)
- First invoke: WAIVED rtl_gen (bus_peripheral, rtl_gen=null → spec-to-rtl), halted phase2 (rtl/ missing) — EXPECTED. Phase 1 = PASS.
- Recovery: authored 4 synthesizable sources (defines.v, user_defines.v, user_proj_example.v, user_project_wrapper.v) into phase2/stage1/rtl/. uprj_netlists.v NOT staged (confirmed absent).
- Re-invoke: Phase 1 SKIPPED(cached PASS), Phase 2 = **PASS_WITH_WAIVERS**, Phase 3 ran FULLY (356.9s, halted_at=phase3 on the 2 known-hold FAILs). Public-tree phase3_one_shot_runner.py (v1.0.60) drove the backend.

## #698 FIELD-VERIFY IN-FLOW — RESOLVED ✅
Fresh THIS-run evidence:
- **Step-31 ERC screen** (`reports/phase3/erc.json`): `verdict: "BENIGN-ERC"`.
  `reports/phase2/gates/erc_density.json`: `erc_clean: true, pass: true, errors_count: 0`,
  finding category `ERC_BENIGN_FLOATS` ("ERC floating nets=3 are 100% structurally benign").
- **Step-28 PERC consumer** (`reports/phase3/perc_equivalent.json`): the "Floating nets"
  category is now `result=REVIEW, source_verdict=BENIGN-ERC`, note="benign float verdict
  from the #696 ERC screen (VPWR/VGND/zer…) — non-blocking review item, not a conclusive
  PERC defect (#698)". Top verdict = `PERC_EQUIV_INCOMPLETE` (driven by EM=MEASURED, NOT
  by the float) — NO LONGER `PERC_EQUIV_FAIL`.
- **Step-28 gate** (`reports/phase2/gates/perc_signoff.json`):
  `verdict: "PASS_WITH_OPEN_ITEMS"`, `reason: "no conclusive reliability defect; 3 named
  open item(s) pending review before tapeout"`, `source_verdict: "PERC_EQUIV_INCOMPLETE"`.
  The round-10 self-contradiction (`verdict: FAIL` / "conclusive PERC reliability defect(s):
  Floating nets: BENIGN-ERC") is GONE.

| | Round-10 | Round-11 (#698) |
|---|---|---|
| ERC screen (Step 31) | BENIGN-ERC → PASS | BENIGN-ERC → PASS |
| PERC "Floating nets" category | result=**FAIL** | result=**REVIEW** |
| perc_equivalent top verdict | PERC_EQUIV_**FAIL** | PERC_EQUIV_**INCOMPLETE** |
| perc_signoff gate (Step 28) | verdict=**FAIL** ("conclusive…defect: BENIGN-ERC") | verdict=**PASS_WITH_OPEN_ITEMS** ("no conclusive…defect") |
| flow_compliance Step 28 | **FAIL** | **PASS** |

→ **#698 RESOLVED in-flow.**

## §4.05 spot-check (by code path, not fabricated) — PASS
Drove the exact `_emit_perc_equivalent._auto()` result mapper directly:
| input verdict | → result | note |
|---|---|---|
| `PASS` | PASS | clean signoff |
| `REVIEW` | REVIEW | legacy review token |
| `BENIGN-ERC` | **REVIEW** | #696 benign float (#698 fix) → non-blocking |
| `MEASURED` | INCOMPLETE | #444 measurement-only |
| `ERC_DIRTY` | **FAIL** | §4.05: genuine functional float STILL FAILs |
| `benign-erc` (lowercase) | **FAIL** | §4.05 no-leak: near-miss NOT swallowed |
| `BENIGN_ERC` (underscore) | **FAIL** | §4.05 no-leak: variant NOT swallowed |
Only the exact `BENIGN-ERC` token maps to REVIEW. A real ERC_DIRTY float and every
near-miss variant still hard-FAIL PERC. The #698 fix is a true allow-list, not a blanket waiver.

## SOLE ACCEPTANCE CRITERION (flow_compliance_check --strict, verbatim header)
```
Steps: 59 total (29/31 executed PASS, 3 DEFERRED via waiver)
  PASS=28  FAIL=2  MISSING=0  WAIVED-DEFERRED=3  SKIPPED=25  VACUOUS-PASS=1
Overall: FAIL  (strict=True)   exit 1
```
**29/31 executed PASS** (UP from r10's 28/31), **3 DEFERRED**, **2 FAIL**.
The FAIL set shrank: r10 = {P0, **Step-28-PERC**, Step-38} → r11 = {P0, Step-38}.
The #698 PERC FAIL is GONE (Step 28 now PASS). Both remaining FAILs are KNOWN holds.

### Full chain per-step verdicts (THIS run)
| Step | Name | Verdict | vs r10 |
|---|---|---|---|
| P0 | Structural-RTL gates | **FAIL** (phase1 L-doc field-depth — KNOWN pre-existing) | = |
| D1 | Phase 1 doc extraction | PASS | = |
| 1 | Spec-to-RTL | PASS | = |
| 2 | Lint | PASS | = |
| 3 | CDC/RDC | SKIPPED-CONDITION (multi-clock; real CDC tool req, #433c) | = |
| 4 | Simulation | WAIVED-DEFERRED (#651 cpu_functional_oracle_waiver) | = |
| 5 | Formal | SKIPPED-CONDITION (#608/#675 no formal tool) | = |
| 6 | FPGA early | WAIVED-DEFERRED (ENV_UNAVAILABLE cap:fpga_board_prototype) | = |
| 7 | Constraint setup (SDC+PVT) | PASS | = |
| 8 | SDC validation | PASS | = |
| 9 | Synthesis | PASS | = |
| 10 | Pre-layout STA | PASS | = |
| 11/12/13 | DFT / post-DFT / LEC | SKIPPED-CONDITION (cap:#430) | = |
| 14 | Synthesis handoff gate | VACUOUS-PASS (input N/A) | = |
| 15 | Floorplan + PDN | PASS | = |
| 16 | Clock planning | PASS | = |
| 17 | Placement | PASS | = |
| 18 | Spare-cell + ECO-prep | PASS | = |
| 19 | CTS | PASS | = |
| 20 | Post-CTS hold fix | PASS | = |
| 21 | Routing (met1-met5) | PASS | = |
| 22 | SPEF extraction | PASS | = |
| 23 | Post-route STA (MCMM) | PASS | = |
| 24 | IR drop | PASS | = |
| 25 | EM | PASS | = |
| 26 | Antenna | PASS | = |
| 27 | Signal Integrity | PASS | = |
| 28 | **PERC / Reliability sign-off** | **PASS** ← #698 RESOLVED (was FAIL r10) | FAIL→PASS |
| 29/30 | post-layout gate-sim SDF + SPICE | SKIPPED-CONDITION (cap:#430) | = |
| 31 | Physical Verification (DRC+LVS+ERC+Density) | PASS | = (#696) |
| 32 | ECO | PASS | = |
| 33 | Power analysis | PASS | = |
| 34 | Metal Fill | PASS | = |
| 35 | DFM screen | PASS | = |
| 36 | Tapeout checklist | PASS | = |
| 37 | GDSII output | PASS | = |
| 38 | Foundry Handoff | **FAIL** (KNOWN roadmap hold — kit assembler not shipped) | = |
| 39 | FPGA final | WAIVED-DEFERRED (ENV_UNAVAILABLE cap:fpga_board_prototype) | = |
| A1-A9/M1-M4 | Analog/Mixed-signal | SKIPPED-CONDITION (no analog content) | = |
| 40-44 | Manufacturing | SKIPPED-CONDITION (no silicon_received) | = |

Full doc→GDS→tapeout chain GREEN: PnR(met1-met5) → CTS → hold-fix → SPEF →
post-route STA → IR/EM/antenna/SI → **PERC(Step 28) PASS** → PV(DRC+LVS+ERC) PASS →
ECO → Power → Metal-Fill → DFM → Tapeout-checklist → **GDSII PASS**.

## Physical sign-off re-confirmation (THIS run, fresh evidence)
- **GDSII**: `phase3/stage4/gds/user_project_wrapper.gds` = **88.66 MB** (MB-scale; also in pnr/ + foundry_handoff/). Step 37 = PASS.
- **DRC**: `reports/phase3/drc_signoff.rpt` (KLayout sign-off DB) = **0 `<item>` violations**.
- **LVS**: `reports/phase3/lvs.json` `passed: true`; `lvs.rpt` = "netgen LVS: circuits match **uniquely** (layout user_project_wrapper vs gate netlist user_project_wrapper_pnr.v)".
- **ERC**: `BENIGN-ERC` (0 functional floats, #696) → Step 31 PV = PASS.
- **PERC**: Step 28 = PASS (PASS_WITH_OPEN_ITEMS; benign-float REVIEW, EM=MEASURED INCOMPLETE — both non-blocking review items, #698).
- Whole-tree gate JSON scan: only FAIL/`pass:false` artifacts are `foundry_handoff_audit.json` (Step 38) + the 3 aggregate roll-ups (vibe_ic / phase3 / phase23 completion audit). NO PERC/ERC/LVS/DRC FAIL anywhere.
- `reports/orchestrator/phase3_one_shot.json`: **`steps_verdict: "PASS"`** (every phase3 backend step PASSes on its own); `verdict: FAIL` only because `completion_audit_verdict: FAIL` (the P0+Step38 holds) and the orchestrator must derive from, not contradict, the completion audit (#437f).

## NEW CHIP-AGNOSTIC FILE-WORTHY GAPS — NONE
No genuinely-new chip-agnostic plugin gap surfaced this round. #698 closed the only
new gap from r10 (the #696-downstream PERC mis-map). The whole-tree FAIL scan shows
zero new failing gate; the phase3 backend `steps_verdict` is a clean PASS.

## CATEGORIZATION OF THE 2 REMAINING FAILs
| FAIL step | Category | Evidence |
|---|---|---|
| **Step P0** (l_doc_structured_field_count_check: 3 L docs under typed-field threshold) | **KNOWN HOLD — phase1 L-doc field-depth** | pre-existing on sparse upstream vendor docs (README+RTL only); explicitly on the task's NON-new list. |
| **Step 38** (foundry_handoff_package_check) | **KNOWN HOLD — foundry-handoff kit assembler (roadmap)** | `rationale_when_skipped: "Foundry-handoff kit assembler not shipped."`; FAIL on `FOUNDRY_HANDOFF_CHIP_GDS_MISSING` + 9 `PENDING_FOUNDRY_*` fields (mask layers, reticle steppers, WAT structures, yield target) that require commercial foundry data. Explicitly on the task's NON-new list. |

## ENVIRONMENT-ONLY / CAP-GAP BLOCKERS (separated from plugin gaps — NOT new, do not file)
- Step 6/39 FPGA — ENV_UNAVAILABLE cap:fpga_board_prototype (no DE10/Quartus on host).
- Step 29/30 SDF gate-sim + SPICE correlation — cap:#430 open-tool chain.
- Step 11/12/13 DFT/post-DFT/LEC — cap:#430.
- Step 3 CDC, Step 5 Formal — SKIPPED-CONDITION (open-tool, #433c/#608/#675).
- Step 4 Simulation — WAIVED-DEFERRED (#651 cpu_functional_oracle_waiver).
None of these is a chip-agnostic PLUGIN gap; all are environment/cap-gap blockers already capped.

## CONVERGENCE VERDICT — CONVERGED ✅
(i) **#698 RESOLVED in-flow** — Step-28 PERC FAIL→PASS on the same BENIGN-ERC benign-float
data; perc_signoff = PASS_WITH_OPEN_ITEMS ("no conclusive reliability defect"); §4.05 no-leak
verified by code path (real ERC_DIRTY + near-miss tokens still FAIL).
(ii) **ZERO new chip-agnostic plugin gaps** — whole-tree FAIL scan = only known-hold steps;
phase3 backend `steps_verdict = PASS`.
(iii) **Every remaining FAIL is a known hold or cap-gap** — Step P0 = phase1 L-doc field-depth
(known pre-existing hold), Step 38 = foundry-handoff kit assembler (known roadmap hold).
The SKIPPED/WAIVED-DEFERRED set is entirely cap-gaps (FPGA / SDF / SPICE / DFT / CDC / Formal).

**Justification (one paragraph mapping each remaining FAIL):** flow_compliance_check r11 = 29/31
executed PASS, 2 FAIL. FAIL-1 = Step P0 l_doc_structured_field_count_check — the phase1 L-doc
typed-field-depth hold that is pre-existing on sparse upstream vendor docs and explicitly enumerated
as NON-new. FAIL-2 = Step 38 foundry_handoff_package_check — the foundry-handoff kit assembler that
is "not shipped" (roadmap) and whose missing fields are PENDING_FOUNDRY commercial data, explicitly
enumerated as NON-new. There is no third FAIL: the #698 PERC gap (the only new gap of r10) is gone,
and the whole-tree gate scan surfaces no other failing gate. All non-PASS-non-FAIL steps are
cap-gaps (FPGA board, SDF/SPICE #430, DFT/LEC #430, CDC #433c, Formal #608/#675) or
no-analog-content SKIPs. Therefore the loop has CONVERGED: the FAIL set is entirely
{known holds + cap-gaps}, with no remaining chip-agnostic plugin gap to capture.

