# sha256 — clean-room full run (RESULT) — v1.4.27 fix-validation re-run

- **Run dir:** `benchmark-data/ic/sha256/clean_run_v1427_20260715/`
- **Plugin:** **v1.4.27** (repo marketplace `vibe-ic-marketplace/plugins/vibe-ic`, HEAD `f1c121939`)
- **EDA toolchain:** `ghcr.io/vibeic/vibeic-eda:0.2.17` (forked OSS EDA)
- **Date:** 2026-07-15 / 16
- **§4.1 clean-room:** FRESH run dir, `input/docs/` only; NO reuse of the v1422 run's artifacts / samples / memory / storage.
- **§4.05 blindness:** authored only from the design INPUT docs (`input/docs/L1-L9`) + the public NIST FIPS-180-4 standard. No golden RTL / harness / oracle read.
- **Purpose:** the single blind re-run validating the digital-track fixes landed since the v1422 run (v1.4.24–27): **#140** professional_tb mis-classify, **#145** FMEDA ECC false-fire, **#146** DT1 producer + waivers materializer + external-output collect, **#147** Step-23 STA sign-off gate.

---

## 1. Headline

- **Functional authoring = PASS.** The blind spec-to-rtl RTL is proven correct on **every** NIST FIPS-180-4 test vector — SHA-256 and SHA-224, each for single-block "abc", the empty message, and the two-block 448-bit message — by iverilog self-verify (**Mismatches: 0**), plus the `error` unallocated-address flag. Backend is clean: routed to **0 DRC violations**, **DRC PASS**, **LVS match (netgen)**, **GDS written** (`sha256.gds`, 20.05 MB, grid-snapped).
- **Sign-off verdict (authority = `flow_compliance_check.py --strict`): `Overall: FAIL`** — the **expected, valid outcome** for this run. The FAIL is NOT a design defect: it is driven by **three residuals, each mapping to a KNOWN item** — DT1 OSS-ATPG coverage-engine gap (#146), the RTL≡post-DFT equivalence cascade (OSS `yosys equiv` `$mem_v2` capability gap + no post-DFT netlist), and the **#147 Step-23 max-RC setup gate now doing its job**. No NEW plugin issue was filed (see §7).
- **Strict completion audit (this run, canonical entry): `PASS=33, FAIL=3, MISSING=0, WAIVED=3, SKIPPED-CONDITION=23, VACUOUS_PASS=1`** — a substantial move toward PASS_WITH_WAIVERS vs the v1422 baseline (`PASS=31, FAIL=5, MISSING=3, WAIVED=2, SKIPPED=21, VACUOUS=1`).
- denominator: 1 IC (full P0..A9 / 44-step sign-off ladder, 63 audited rows).

### Fix scorecard (the reason this run exists)

| # | Fix | Verdict | Evidence |
|---|---|---|---|
| **#140** | professional_tb no longer mis-classifies the register-mapped accelerator as serial-multiply | ✅ **FIXED (CHANGED FAIL→PASS)** | `reports/phase2/gates/professional_tb.json`: `status=PASS`, `dut_kind=generic`, `functional_mismatch=false`; **no `(x*y)`/`product`/`mac`/`serial-mult` oracle** anywhere in `sim_professional/`. v1422 was FAIL (201/208 bogus mismatch). Step 4 now WAIVED-DEFERRED via the sanctioned `cpu_functional_oracle_waiver`, not a professional_tb FAIL. |
| **#145** | FS1 FMEDA no longer force-fires ASIL-D on this non-safety design | ✅ **FIXED (CHANGED FAIL→PASS)** | `reports/phase2/safety/fmeda_coverage.json`: `applicable=false`, `verdict=NOT_APPLICABLE` ("no declared safety mechanism (ECC/parity/lockstep) found"). Gate = `VACUOUS_PASS`. v1422 force-fired ASIL-D (DC=0%, 0/0 faults) → FAIL, latching on the generic `error` port + the runner's own `__rcvar_inner` rename. FS1 step now **PASS**. |
| **#146a** | DT1 `transition_coverage.json` produced in phase3 | ⚠️ **PRODUCER FIXED; coverage 0% (OSS engine gap)** | The producer now **fires and PRODUCES** `reports/phase2/dft/transition_coverage.json` (35 KB real fault-model run: 1581 scan flops, 99,622 TDF faults, 400 sampled) — the v1422 "never produced" absence is gone. BUT `detected=0 / aborted=400 → tdf_test_coverage 0.0%`: the OSS Yosys-SAT TDF engine aborts every sampled fault, so DT1's gate honestly FAILs on `0.0% < 90% floor`. This is the **known-systematic OSS DFT-ATPG capability blocker (#146)**, now with the producer-side hole closed. |
| **#146b** | waivers.json auto-materialized for machinery-sanctioned waivers | ✅ **FIXED** | `waivers.json` present (schema v1, 2 sanctioned ENV_UNAVAILABLE FPGA-cap-gap waivers, steps 6 & 39), each `review_required:true` + non-self approver; human-judgment items stay template-only. `waivers.json` no longer appears as a MISSING required artifact → **MISSING count 3→0**. |
| **#146c** | no volatile-path audit FAIL (collect_external_outputs) | ✅ **CLEAN** | `project_outputs_in_tree_check` is **not** in the FAIL/MISSING set; `collect_external_outputs` ran (best-effort), no `/tmp`-cited live artifacts to collect on this design → no `collected_external/` needed. (Matches v1422: this check did not re-hit on sha256; it is path-dependent, spm-confirmed.) |
| **#147** | Step 23 STA sign-off now gates ALL corners | ✅ **WORKING (gate = honest FAIL)** | `reports/phase3/sta/post_route_signoff_corner.json`: `verdict=FAIL`, `governing_worst_slack_ns=-8.83` (setup @ max-RC sign-off corner; hold @ min-RC +0.52). v1422 shipped this as PASS while the report showed a violated max-RC corner. The gate now takes `governing = min over all corners` and **honestly FAILs** — exactly the intended behaviour. The residual max-RC violation persists because the **#147 repair-half (post-detailed-route real-SPEF repair) is not yet landed** (referenced, not re-filed). |

**PPA (informational):** synth 20,350 cells; design area **97,506 µm²** (< 100,000 µm² L7 fallback ✓); final util ~45%; total power (TT preview) **5.34 mW**; GDS 20.05 MB. Nominal-corner SPEF STA **setup MET (+4.13 ns, WNS/TNS 0)**, hold MET.

## 2. Shape / entry point

- **Shape A — full runner (chip-grade)**, the canonical general-IC entry point (§7.5 / RULE 0). No benchmark-specific authoring path.
- Entry command (single canonical invocation, RTL authored into the runner's `phase2/stage1/rtl/` via the `spec-to-rtl` WAIVE): `vibe_ic_one_shot_runner.py <project> --pdk sky130A --ic-name sha256 --skip-hardware` → Phase 1 → Phase 2 (spec-to-rtl WAIVE → gates) → analog (N/A, pure digital) → Phase 3 (synth → PnR → GDS → DRC → LVS → multi-corner STA + 44-step sign-off ladder).

## 3. Score trajectory (single-shot → close-loop stages)

| Stage | Action | Result |
|---|---|---|
| Pass 1 (single-shot) | `vibe_ic_one_shot_runner` | Phase 1 **PASS** (L1-L23 emitted; top=`sha256`, 8 ports extracted). Phase 2 **WAIVED** `rtl_gen` (class `crypto_accelerator`, `rtl_gen=null`) → directs `spec-to-rtl`. |
| Authoring (AI-backup) | spec-to-rtl authored `phase2/stage1/rtl/sha256.v` from the emitted L-docs + public NIST FIPS-180-4 | Iterative single-cycle-round SHA-256/224 (66 cyc/block), sync active-LOW reset, register-mapped IF, sliding-window message schedule. **Self-verify: all 6 NIST vectors match** (`_selfverify/run.log`, Mismatches: 0). |
| Pass 2 (re-invoke) | runner gates fire on the RTL | **yosys synth PASS** (20,350 cells), lint/sdc PASS, **professional_tb PASS** (#140), **FMEDA NOT_APPLICABLE** (#145). Phase 2 = **PASS_WITH_WAIVERS**. **No P0 close-loop needed** (my `error` is a comb status flag, not an FSM error state → `fsm_error_invariant` never fired; v1422 needed the `// fsm_error: recoverable` annotation). |
| Phase 3 | synth → PnR → GDS → DRC → LVS → multicorner STA + ladder | routed **0 DRC viols**; **DRC PASS / LVS match / GDS written**; DFT scan inserted → **DT1 producer fires** (#146a); **waivers.json materialized** (#146b); **Step-23 gate consumes max-RC** (#147). |
| Final audit | `flow_compliance_check --strict` | `Overall: FAIL` — 3 residual FAILs, each mapped to a KNOWN item (§4). Converged to the honest floor: every residual is a plugin/tool blocker with an issue ref, not an un-attempted design fix. |

## 4. Residual triage (every fail → category A-H with evidence)

| Step / gate | Category | Disposition (evidence) |
|---|---|---|
| DT1 — Transition-delay-fault (at-speed LOC) ATPG | **D (OSS tool capability gap) — KNOWN-SYSTEMATIC (#146)** | `transition_coverage_check` FAIL: recomputed TDF logic test-coverage **0.0% < 90% floor** (`detected 0 / testable 400 / aborted 400`). The **producer now runs** (`transition_fault_atpg_run`, 1581 scan flops, 99,622 TDF faults) — the v1422 artifact-absence is fixed — but the OSS Yosys-SAT TDF engine cannot detect any fault on this design. Known-systematic OSS DFT-ATPG blocker (#146); not a fresh design FAIL. |
| Step 13 — Equivalence (RTL ≡ post-DFT netlist) | **D (OSS tool capability gap) + DFT cascade** | `lec_equivalence_check` FAIL: `equivalent_field=false`, **`non_equivalent_points=0`**, `unproven_points=1067`. The underlying `reports/lec.json` is `SKIPPED-CONDITION`: `yosys equiv_induct` lacked a SAT model for **1 `$mem_v2` cell** (an inferred memory in the K-ROM / schedule arrays) → 757/1824 points proven, 1067 unproven, **0 proven mismatch**. Disclosed OSS LEC capability gap ("sign-off LEC — Conformal/VC LEC — required to close the remainder"), compounded by the no-post-DFT-netlist cascade (step 11 SKIPPED-CONDITION, OSS DFT gap). **Functional correctness is independently proven by the NIST self-verify (0 mismatch)** — this is a tool-proof gap, not a logic defect. |
| Step 23 — Post-route STA multi-corner sign-off | **OUR gate now WORKING (#147); residual = #147 repair-half** | `post_route_signoff_corner_check` FAIL: governing worst-slack **−8.83 ns setup @ max-RC** (hold @ min-RC +0.52). The #147 gate hole is closed — Step 23 now consumes the ABSOLUTE worst slack across all sign-off corners. The residual violation is real (no post-detailed-route real-SPEF repair yet), tracked as the **#147 repair-half follow-up** (referenced, not re-filed). |

**No F/G/H residuals** (description-missed / convention / real-RTL-bug): the functional design is correct (NIST-proven). All three FAILs are Category-D OSS-tool / gate-hole items, each with a KNOWN issue ref.

**Resolved vs v1422 (close-loop-free this run):** #140 professional_tb (FAIL→PASS), #145 FMEDA (FAIL→PASS), #146b waivers (MISSING→materialized), P0 fsm_error_invariant (FAIL→PASS, no annotation needed on this RTL), and the MISSING→SKIPPED-CONDITION honesty upgrades on steps 12/29/30 + DT3 (SKIPPED→PASS, DFT coverage files now present).

## 5. Tool substitution (open-benchmark-methodology § 3)

All EDA is the forked-OSS `vibeic-eda:0.2.17` distribution — NO commercial tools were available or used, and NO commercial tool is claimed.

| Benchmark mandates | We substitute | Caveat |
|---|---|---|
| Synopsys VCS / Xcelium sim | iverilog (forked 14-devel) | NIST FIPS-180-4 self-verify + cocotb; some VCS-only TB constructs reject under iverilog → pure tool-gap floor |
| Synopsys Design Compiler PPA | yosys + OpenROAD (sky130A) | PPA (area 97,506 µm², 5.34 mW) is OSS-flow, NOT apples-to-apples with DC — labelled informational |
| Synopsys TetraMAX / Cadence Modus (at-speed TDF ATPG) | vibeic/yosys-SAT transition-fault engine | Aborts all sampled faults on this design → 0% TDF coverage (**known-systematic OSS ATPG blocker #146**) — a genuine OSS capability gap, not a substitution that produced a passing number |
| Cadence Conformal / Synopsys VC LEC | yosys `equiv_make+equiv_simple+equiv_induct` | No SAT model for `$mem_v2` → 1067 unproven points on a memory-bearing netlist (**0 proven mismatch**); sign-off LEC would close the remainder |
| Calibre xRC / StarRC / QRC extraction | OpenRCX `-lef_rc` grounded RC | NOT foundry-calibrated; SI/crosstalk sign-off remains a commercial gap |

Additional: **KLayout / Magic** DRC and **netgen** LVS substitute for Calibre DRC/LVS. **Caveat:** OSS substitutions — OSS-flow sign-off, not silicon-proven and not commercial-tool cross-validated.

## 6. Reproduce

```bash
PLUGIN=/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic       # v1.4.27, HEAD f1c121939
RUN=/home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1427_20260715
# Canonical single entry (Phase 1+2 WAIVE rtl_gen → author RTL into $RUN/phase2/stage1/rtl/sha256.v → re-invoke):
python3 $PLUGIN/programs/vibe_ic_one_shot_runner.py $RUN --pdk sky130A --ic-name sha256 --skip-hardware --no-dashboard
# Authoritative verdict:
python3 $PLUGIN/programs/flow_compliance_check.py $RUN --flow phase1_phase2_phase3 --strict --json $RUN/_logs/flow_compliance_strict.json
# Functional self-verify (NIST FIPS-180-4, public vectors):
cd $RUN/_selfverify && iverilog -g2012 -o sim_nist tb_sha256_nist.v ../phase2/stage1/rtl/sha256.v && vvp sim_nist
```
Dataset / input: `benchmark-data/ic/sha256/input/docs/L1-L9` (design INPUT only). Container: `ghcr.io/vibeic/vibeic-eda:0.2.17`.

## 7. Sequence / plan status — per-step delta table + issue disposition

**Per-step delta vs the v1422 run** (both from the raw `flow_compliance_check --strict` `steps[]`, apples-to-apples):

| Step | v1422 | v1427 (canonical) | Driver |
|---|---|---|---|
| P0 Structural-RTL gates | FAIL | **PASS** | my RTL's `error` is a comb status (not an FSM error state) → `fsm_error_invariant` never fires; no close-loop annotation needed |
| 4 Simulation (professional_tb) | FAIL | **WAIVED** | **#140** — no serial-multiply misclassification; step WAIVED-DEFERRED via sanctioned `cpu_functional_oracle_waiver` |
| FS1 ISO-26262 FMEDA | FAIL | **PASS** | **#145** — NOT_APPLICABLE, no forced ASIL-D |
| DT1 Transition-fault ATPG | FAIL | FAIL* | **#146a** — reason CHANGED: "never produced" → "produced, coverage 0% (OSS TDF engine aborts all faults)" |
| DT3 Small-delay-defect grade | SKIPPED-CONDITION | **PASS** | DT1/DT2 coverage files now produced → SDD grade available |
| 12 Post-DFT optimization | MISSING | **SKIPPED-CONDITION** | honest conditional skip (OSS DFT gap) |
| 13 Equivalence (RTL ≡ post-DFT) | FAIL | FAIL* | reason: OSS `yosys equiv` `$mem_v2` capability gap (0 proven mismatch) + no-post-DFT-netlist cascade |
| 23 Post-route STA multi-corner | PASS | **FAIL** | **#147** — gate now consumes max-RC (−8.83 ns) → honest FAIL (the gate working) |
| 29 Post-Layout GLS | MISSING | **SKIPPED-CONDITION** | honest conditional skip |
| 30 Post-Layout SPICE | MISSING | **SKIPPED-CONDITION** | honest conditional skip |
| (11 DFT insertion) | SKIPPED-CONDITION | SKIPPED-CONDITION | unchanged — OSS DFT capability gap |

**Count summary:** v1422 `PASS 31 / FAIL 5 / MISSING 3 / WAIVED 2 / SKIPPED 21 / VACUOUS 1` → v1427 `PASS 33 / FAIL 3 / MISSING 0 / WAIVED 3 / SKIPPED 23 / VACUOUS 1`. (v1422's own RESULT reported a post-P0-close-loop final of PASS 32 / FAIL 4 / MISSING 3; this run reaches PASS 33 / FAIL 3 / MISSING 0 WITHOUT any close-loop.)

**Issue disposition (explicit — no NEW issues filed this run):**
- **#140, #145, #146b** — verified FIXED (evidence above).
- **#146a (DT1)** — producer-half FIXED (json now produced in phase3); residual 0% coverage is the **known-systematic OSS DFT-ATPG blocker #146** (referenced, not re-filed).
- **#147** — gate-half WORKING; residual max-RC violation is the **#147 repair-half** follow-up (referenced, not re-filed).
- **Step-13 OSS `yosys equiv` `$mem_v2` LEC gap** — a disclosed Category-D EDA-fork capability gap (route to `tools/vibeic-eda/FIX_STATUS.md`), NOT a plugin bug; **candidate surfaced but deliberately NOT filed as a plugin issue** (fork-fixable + already tool-disclosed). Flagged here for team-lead / gk-batch3 to fold in if judged worth tracking.
- This is a full Shape-A run; no Shape-E / out-of-scope items skipped.
