# RESULT — caravel_user_project (7th benchmark IC), Round 10 (convergence-confirmation)

Clean-room close-loop. Plugin **v1.0.59** (public tree, PUSHED), **#696 fixed**
(ERC floating-net benign-class allow-list: VPWR/VGND power rails + zero_ hilomap
tie + spare_* ECO-pool pins no longer counted as functional floats).

- Runner: `/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/vibe_ic_one_shot_runner.py` (PUBLIC TREE, v1.0.59)
- Run dir: `_bench7_caravel_v1034_cleanroom/caravel_r10` (clean-room: input/ ONLY)
- PDK sky130A, ic=caravel_user_project, top=user_project_wrapper, die 2920x3520
- Shape A/D. Blind: no reference GDS / spm_pilot / host-scorer.
- Round-9 baseline: Overall FAIL, 28/31 executed PASS, 3 DEFERRED, 3 FAIL
  (P0 phase1-depth | Step-31 ERC floating-net [the #696 gap] | Step-38 foundry-handoff).

## Pre-run code confirmation of #696 (public tree)
- `erc_density_check.py` (v1.0.59): a raw floating-net count>0 is no longer an
  automatic FAIL; floats are classified BY OWNER via `erc_float_owner_classify`.
  `functional==0` → `INFO ERC_BENIGN_FLOATS` (pass). A genuine functional signal
  float (not spare/power-ground/tie) → `ERROR ERC_DIRTY` FAIL (§4.05 preserved).
  An unparseable report with no float list also still FAILs (no waive on faith).
- `erc_float_owner_classify.py`: whole-name anchored power/ground (sky130
  VPWR/VGND/VPB/VNB + VCCD/VSSD families, gf180 VDD/VSS, generic vdd/vss/vcc/gnd)
  + hilomap tie (zero_/one_/tie*) + spare-owned pins. A real signal merely
  CONTAINING 'vdd'/'zero' as substring is NOT swallowed (§4.05 no-leak).

<!-- APPEND after each major Phase-3 step -->

## Run log (re-invoke with recovered RTL)
- First invoke: WAIVED rtl_gen (bus_peripheral, rtl_gen=null → spec-to-rtl), halted phase2 (rtl/ missing) — EXPECTED.
- Recovery: authored 4 synthesizable sources (defines.v, user_defines.v, user_proj_example.v, user_project_wrapper.v) into phase2/stage1/rtl/. uprj_netlists.v NOT staged (asserted absent).
- Re-invoke Phase 2: **PASS_WITH_WAIVERS** — yosys_synth PASS (netlist_yosys.v, cells=189, top=user_project_wrapper). Phase 1 PASS (24/13 L docs). Phase 3 entered.

## #696 FIELD-VERIFY IN-FLOW — RESOLVED ✅
THIS-run fresh evidence (`reports/phase2/gates/erc_density.json`):
- `pass: true`, `erc_clean: true`, `errors_count: 0`, `findings_count: 2`.
- Finding category = **`INFO ERC_BENIGN_FLOATS`** (NOT the round-9 `ERROR ERC_DIRTY`).
- Message: "ERC floating nets=3 are 100% structurally benign (spare-cell I/O /
  power-ground rails / hilomap tie net … by_owner={spare_aoi_0:3, spare_dff_0:3,
  spare_mux2_0:3, spare_nand2_0:2, spare_nor2_0:2, VGND:1, VPWR:1, zero_:1,
  spare_inverter_0:1, spare_inverter_1:1}) — **0 functional floats** … (#696)".
- Raw `reports/phase3/erc.rpt` shows the SAME 3 floats (VGND, VPWR, zero_) + 15
  `spare_*` pins as round-9 — identical layout, only the *classification* changed.

By-owner classification (THIS run):
| owner | count | class |
|---|---|---|
| VPWR | 1 | power rail (SPECIALNET) → benign |
| VGND | 1 | ground rail (SPECIALNET) → benign |
| zero_ | 1 | yosys hilomap constant-tie → benign |
| spare_aoi_0 | 3 | ECO spare-cell I/O → benign |
| spare_dff_0 | 3 | ECO spare-cell I/O → benign |
| spare_mux2_0 | 3 | ECO spare-cell I/O → benign |
| spare_nand2_0 | 2 | ECO spare-cell I/O → benign |
| spare_nor2_0 | 2 | ECO spare-cell I/O → benign |
| spare_inverter_0/1 | 2 | ECO spare-cell I/O → benign |
| **FUNCTIONAL** | **0** | → ERC pass (no electrical-rule failure) |

Round-9 ERC gate: `ERROR ERC_DIRTY: floating nets=3` (FAIL).
Round-10 ERC gate: `INFO ERC_BENIGN_FLOATS … 0 functional floats` (PASS). → #696 RESOLVED.

## §4.05 spot-check (by code path, not fabricated) — PASS
Drove `erc_float_owner_classify.classify()` directly:
- CASE 1 (round-10 benign set only): functional_count=0, classification=`benign-ERC`, waiver_eligible=True → ERC PASS. ✓
- CASE 2 (same benign set + genuine functional float `data_out_valid`): functional_count=1, functional_floats=['data_out_valid'], classification=`has-functional-floats`, waiver_eligible=False → ERC FAIL. ✓ (fix still FAILs on a real signal float)
- CASE 3 (§4.05 no-leak): `vdd_ok`, `data_zero_flag`, `pll_vdd_sel` → all 3 functional (NOT swallowed by substring 'vdd'/'zero'). ✓
The #696 allow-list is a true allow-list, not a blanket waiver: genuine functional floats still hard-FAIL.

## SOLE ACCEPTANCE CRITERION (flow_compliance_check --strict, verbatim header)
```
Steps: 59 total (28/31 executed PASS, 3 DEFERRED via waiver)
  PASS=27  FAIL=3  MISSING=0  WAIVED-DEFERRED=3  SKIPPED=25  VACUOUS-PASS=1
Overall: FAIL  (strict=True)   exit 1
```
28/31 executed PASS (same count as round-9), **3 DEFERRED**, **3 FAIL**. The FAIL
SET CHANGED vs round-9 — the #696 ERC FAIL is GONE (Step 31 now PASS), but Step 28
PERC newly FAILs on the SAME benign-float data (see "NEW GAP" below).

### Full chain per-step verdicts (THIS run)
| Step | Name | Verdict |
|---|---|---|
| P0 | Structural-RTL gates | **FAIL** (phase1 L-doc field-depth — KNOWN pre-existing) |
| D1 | Phase 1 doc extraction | PASS |
| 1 | Spec-to-RTL | PASS |
| 2 | Lint | PASS |
| 3 | CDC/RDC | SKIPPED-CONDITION (multi-clock; real CDC tool required, #433c) |
| 4 | Simulation | WAIVED-DEFERRED (#651 cpu_functional_oracle_waiver) |
| 5 | Formal | SKIPPED-CONDITION (#608/#675 no formal tool) |
| 6 | FPGA early | WAIVED-DEFERRED (ENV_UNAVAILABLE cap:fpga_board_prototype) |
| 7 | Constraint setup (SDC+PVT) | PASS |
| 8 | SDC validation | PASS |
| 9 | Synthesis | PASS |
| 10 | Pre-layout STA | PASS |
| 11/12/13 | DFT / post-DFT / LEC | SKIPPED-CONDITION (cap:#430) |
| 14 | Synthesis handoff gate | VACUOUS-PASS (input N/A) |
| 15 | Floorplan + PDN | PASS |
| 16 | Clock planning | PASS |
| 17 | Placement | PASS |
| 18 | Spare-cell + ECO-prep | PASS |
| 19 | CTS | PASS |
| 20 | Post-CTS hold fix | PASS |
| 21 | Routing (met1-met5) | PASS |
| 22 | SPEF extraction | PASS |
| 23 | Post-route STA (MCMM) | PASS |
| 24 | IR drop | PASS |
| 25 | EM | PASS |
| 26 | Antenna | PASS |
| 27 | Signal Integrity | PASS |
| 28 | **PERC / Reliability sign-off** | **FAIL** ← NEW (BENIGN-ERC float mis-mapped to FAIL; see below) |
| 29/30 | post-layout gate-sim SDF + SPICE | SKIPPED-CONDITION (cap:#430) |
| 31 | **Physical Verification (DRC+LVS+ERC+Density)** | **PASS** ← #696 RESOLVED (was FAIL in r9) |
| 32 | ECO | PASS |
| 33 | Power analysis | PASS |
| 34 | Metal Fill | PASS |
| 35 | DFM screen | PASS |
| 36 | Tapeout checklist | PASS |
| 37 | GDSII output | PASS |
| 38 | Foundry Handoff | **FAIL** (KNOWN roadmap hold — kit assembler not shipped) |
| 39 | FPGA final | WAIVED-DEFERRED (ENV_UNAVAILABLE cap:fpga_board_prototype) |
| A1-A9/M1-M4 | Analog/Mixed-signal | SKIPPED-CONDITION (no analog content) |
| 40-44 | Manufacturing | SKIPPED-CONDITION (no silicon_received) |

Full doc→GDS→tapeout chain GREEN: PnR(met1-met5) → CTS → hold-fix → SPEF →
post-route STA → IR/EM/antenna/SI → **PV(DRC+LVS+ERC) PASS** → ECO → Power →
Metal-Fill → DFM → Tapeout-checklist → **GDSII PASS**. (Step 37 GDSII PASSes.)

## NEW CHIP-AGNOSTIC FILE-WORTHY GAP (HIGH) — #696 not propagated to the PERC consumer (Step 28)
**Symptom:** Step 31 ERC now PASSes (#696), but Step 28 PERC/Reliability sign-off
NEWLY FAILs on the SAME floating-net data. Round-9: Step 28 = PASS_WITH_OPEN_ITEMS.
Round-10: Step 28 = FAIL.

**Fresh THIS-run evidence:**
- `reports/phase3/erc.json` source_verdict = **`BENIGN-ERC`** (the #696 token; was `REVIEW` in r9).
- `reports/phase3/perc_equivalent.json` "Floating nets" category: `"result": "FAIL"`,
  `"source_verdict": "BENIGN-ERC"` → top verdict `PERC_EQUIV_FAIL`.
- `reports/phase2/gates/perc_signoff.json`: `verdict: "FAIL"`,
  `reason: "conclusive PERC reliability defect(s): Floating nets: BENIGN-ERC"`
  — self-contradictory (a defect that is labelled BENIGN).

**Root cause (chip-AGNOSTIC, traced):** `phase3_one_shot_runner._emit_perc_equivalent`,
the `_auto()` status mapper (≈ lines 10164-10165):
```python
result = "PASS" if verdict == "PASS" else (
    "REVIEW" if verdict == "REVIEW" else
    "INCOMPLETE" if verdict == "MEASURED" else "FAIL")
```
The mapper knows `PASS`/`REVIEW`/`MEASURED` but NOT the new `BENIGN-ERC` token #696
introduced (the same file emits it at ≈ line 9713). `verdict == "BENIGN-ERC"` falls
through to `else → "FAIL"`. There is even an in-file precedent comment (#444): a
`MEASURED` verdict was being mis-mapped to FAIL and "made the PERC memo contradict
a step gate reading the same artifact" — IDENTICAL pathology, now for `BENIGN-ERC`.

**Why it is genuinely NEW (not a known hold):** masked in round-9 because the pre-#696
ERC verdict was `REVIEW`, which the mapper DOES recognise (→ non-blocking REVIEW →
Step 28 PASS). #696 changed the token to a MORE-benign `BENIGN-ERC`, which the
downstream PERC consumer was never taught about. Same gate-consistency class as #692
(propagate one gate's benign attestation to the parallel sign-off gate).

**CHIP-AGNOSTIC:** any sky130/open-flow digital P&R with VPWR/VGND specialnets +
hilomap tie + design-for-ECO spare pool produces `BENIGN-ERC` and hits this exact
PERC mis-map — not caravel-specific.

**Fix (for Core Agent):** teach `_emit_perc_equivalent._auto()` (and any
`perc_signoff_check` consumer) that `BENIGN-ERC` maps to a non-blocking result
(REVIEW/PASS-with-open-item), exactly as the old `REVIEW` did and as #444 did for
`MEASURED` — so a benign-ERC float is not a "conclusive PERC reliability defect."
§4.05 preserved: a real `ERC_DIRTY`/functional float still maps to FAIL.

## Physical sign-off re-confirmation (THIS run, fresh evidence)
- **GDSII**: `phase3/stage4/gds/user_project_wrapper.gds` = **89 MB** (MB-scale). Step 37 GDSII = PASS.
- **DRC**: `reports/phase3/drc_signoff.rpt` (KLayout sign-off DB) = **0 violations** (0 `<item>` entries).
- **LVS**: `reports/phase3/lvs_verdict.json` = `LVS_MATCH` — "circuits match **uniquely**" (`lvs.json` terminal_verdict=MATCH, passed=true).
- **ERC**: `BENIGN-ERC` (0 functional floats, #696). → Step 31 PV (DRC+LVS+ERC+Density) = **PASS**.
- Chain met1-met5 routing, CTS, SPEF, post-route MCMM STA, IR/EM/antenna/SI all PASS; ECO/Power/Metal-Fill/DFM/Tapeout-checklist all PASS.

## CONVERGENCE VERDICT — NOT CONVERGED
One genuinely NEW chip-AGNOSTIC plugin gap surfaced THIS round: #696 fixed the ERC
screen (Step 31) but the new `BENIGN-ERC` token was not propagated to the parallel
PERC consumer (Step 28 `_emit_perc_equivalent._auto()` mapper + `perc_signoff_check`),
so Step 28 newly FAILs on the SAME benign-float data that Step 31 now passes. This is
the direct, predictable downstream of #696 (same gate-consistency class as #692/#444).
The other 2 FAILs are known holds (P0 phase1 field-depth; Step 38 foundry-handoff kit).
Because the FAIL set is NOT entirely {known holds + cap-gaps + pre-existing-phase1} —
it contains one new chip-agnostic plugin gap — the loop has NOT converged. A round-11
after the PERC-consumer fix should confirm convergence (expected residual: P0 +
Step 38 + cap-gaps only).

### NEW gap to file (HIGH) — for the Core Agent via ORGANIC backlog
- Title (chip-agnostic): "PERC/reliability sign-off counts a BENIGN-ERC floating-net
  result as a conclusive defect — benign-net ERC verdict not propagated to the PERC
  consumer."
- Root: `phase3_one_shot_runner._emit_perc_equivalent._auto()` status mapper drops
  the `BENIGN-ERC` token to `else→FAIL`; downstream `perc_signoff_check` then reports
  "conclusive PERC reliability defect(s): Floating nets: BENIGN-ERC".
- Fix shape: map `BENIGN-ERC` to a non-blocking result (REVIEW/PASS-with-open-item),
  exactly as `REVIEW` and (#444) `MEASURED` are; keep §4.05 (real ERC_DIRTY → FAIL).

### Known holds / cap-gaps (NOT new — do not file)
- Step P0 phase1 L-doc field-depth — pre-existing on sparse vendor docs.
- Step 38 foundry-handoff package — roadmap hold (kit assembler not shipped).
- Step 6/39 FPGA — ENV_UNAVAILABLE cap:fpga_board_prototype (no DE10/Quartus).
- Step 29/30 SDF gate-sim + SPICE correlation — cap:#430 open-tool chain.
- Step 11/12/13 DFT/post-DFT/LEC — cap:#430.
- Step 3 CDC, Step 5 Formal — SKIPPED-CONDITION (open-tool, #433c/#608/#675).

## NOTE on the +696/-PERC net count
Round-9: 28/31 PASS, FAILs = {P0, Step-31-ERC, Step-38}.
Round-10: 28/31 PASS, FAILs = {P0, **Step-28-PERC**, Step-38}.
The headline 28/31 is unchanged, but ERC (Step 31) moved FAIL→PASS (#696 resolved)
while PERC (Step 28) moved PASS→FAIL (the new #696-downstream gap). Net new
chip-agnostic plugin gaps this round = 1.
