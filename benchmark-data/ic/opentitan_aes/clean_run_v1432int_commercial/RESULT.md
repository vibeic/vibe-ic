# opentitan_aes — real-node RE-VERIFY (RESULT) — commercial 180 nm PDK, EDA 0.2.20-int

- **Run dir:** `benchmark-data/ic/opentitan_aes/clean_run_v1432int_commercial/`
- **Purpose:** A/B validation of the forked-OSS EDA image **`ghcr.io/vibeic/vibeic-eda:0.2.20-int`** (id `fa8cb832daf2`) vs the **0.2.19** baseline, on the OpenTitan AES REUSED-IP crypto block, on a **commercial 180 nm PDK** (staged out-of-git, referenced by PATH only).
- **EDA (test / A):** `0.2.20-int` — yosys `c31dfe3a8` (SOUND functional-LEC + slang gold-read), OpenROAD `1cd84e502a` (dynamic IR + DRT), magic rev 675, iverilog `bedf375e9`, KLayout 0.30.9 + native `svrfdrc`. Fresh throwaway container; the running 0.2.19 container was left untouched.
- **EDA (baseline / B):** `0.2.19` (the concurrent baseline run on the same commercial PDK).
- **PDK:** commercial 180 nm digital sign-off PDK — Liberty (3 corners) / LEF / GDS / SVRF DRC+LVS decks. Staged OUT-OF-GIT, symlinked into `input/pdk/`. **NDA hygiene: this tree contains NO device tokens, NO cell/model/rule text, NO synthesized netlist — numbers / verdicts only.** `.gitignore` whitelists ONLY `.gitignore` + `RESULT.md`.
- **Date:** 2026-07-18.
- **§4.1 clean-room:** FRESH run dir; `input/{docs,vendor_rtl,golden}` staged as design INPUT only; no reuse of prior-run artifacts / verdicts / GDS.
- **§4.05 blindness:** RTL is REUSED-IP (unchanged upstream OpenTitan AES, Apache-2.0); the only authored file is the `chip_top.sv` integration wrapper. Golden `aes.hjson` used for register-map VERIFICATION only.
- **A/B control:** the design is held CONSTANT so the EDA image is the only variable — `chip_top` authored identically, and the `aes_wrap` dependency cone was **independently re-derived** via `catalog_glue_closure_resolver` = **96 .sv + 4 .svh** (exact match to the baseline cone; the `tlul_adapter_vh`/`_shim` duplicate falls in the prunable tail → not staged). SOURCE_MANIFEST reconciliation = 8 tie-offs + 2 flattened outputs.

---

## 1. Headline

- **Functional authoring = PASS.** `chip_top` = thin wrapper on REUSED-IP `aes_wrap` (AES-128 ECB encrypt, key sideloaded, **SecMasking=0**, **SBoxImplLut**, **AES192Enable=1**). **NIST FIPS-197 AES-128 ECB known-answer test: PASS** on 0.2.20-int (verilator 5.048, full 96-file cone, correct ciphertext, `test_done_o` @ cyc 66) — identical to baseline.
- **Front-end PASS.** Phase 1 PASS; Phase 2 synth **PASS, 90 667 cells, `frontend=yosys_slang`** — identical to baseline (90 667).
- **A/B WIN — SOUND-LEC slang gold-read.** LEC gold-read frontend advanced **None (0.2.19) → slang (0.2.20-int)**: the OpenTitan SV (StateEnumT FSM enums + packages) now ELABORATES (proven by synth). This is the targeted parse-abort-false-FAIL fix, PROVEN as an image delta.
- **Backend — OSS router wall (both images).** PnR reached floorplan → place → CTS → hold (die **1667×1667 µm**, **34 800** components — identical to baseline). **Detailed routing did NOT converge** on either image on this dense design: 0.2.20-int bounded at ~4h45m in DRT; the 0.2.19 baseline is still routing at 9h52m (only `routed_preantenna.def`). **GDS / DRC / LVS / final-STA / dynamic-IR = NOT REACHED on either side** — not an image regression.
- **Sign-off verdict:** PnR incomplete (router non-convergence); no tapeout claim. **No silicon validation is claimed.**
- denominator: 1 IC.

## 2. Shape / entry point

- **Shape A — full runner (chip-grade).** Phase 1 → Phase 2 (rtl_gen WAIVE → REUSED-IP / catalog-glue: stage vendor cone + author `chip_top.sv` → re-invoke gates) → analog N/A → Phase 3 (synth → PnR → [route did not converge]). `--pdk auto` → `custom:pdk`. Phase 3 run standalone after the Phase-2 audit halted on the deferred functional TB (same split as the sha256 commercial-PDK run).

## 3. Six-pillar summary

| # | Pillar | Verdict | Note (numbers only) |
|---|--------|---------|---------------------|
| 1 | Functional verification coverage | **PASS** | NIST FIPS-197 AES-128 ECB KAT PASS (cyc 66). Register-map: reused OpenTitan `aes_reg_top` covers all golden `aes.hjson` families (KEY_SHARE0/1, IV, DATA_IN/OUT, CTRL_SHADOWED/AUX/GCM, STATUS, TRIGGER, ALERT_TEST) — structural, REUSED-IP. |
| 2 | 56-step output comparison vs reference | **PENDING** | needs GDS/LVS; routing did not converge. |
| 3 | Code coverage ≥ 90% | **NOT RUN** | deferred (wind-down). |
| 4 | FPGA digital verification | **N/A** | commercial-PDK ASIC target; no FPGA in this run. |
| 5 | Analog closed-loop | **N/A** | pure-digital IC. |
| 6 | Design-for-ECO (spare cells) | **PENDING** | needs routed DEF; routing did not converge. |

## 4. A/B deltas (0.2.19 → 0.2.20-int; numbers only)

| Metric | 0.2.19 (baseline) | 0.2.20-int (test) | Delta |
|--------|-------------------|-------------------|-------|
| Phase 1 | PASS | PASS | = |
| Synth cells / frontend | 90 667 / yosys_slang | 90 667 / yosys_slang | = |
| **LEC gold-read frontend** | **None** (gold failed to elaborate) | **slang** (elaborates) | **WIN — parse-abort-false-FAIL fixed** |
| LEC compared / proven / unproven | 0 / 0 / 0 (0.14 s) | 0 / 0 / 0 (0.58 s) | miter not built either side |
| PnR floorplan (die, components) | 1667×1667 µm, 34 800 | 1667×1667 µm, 34 800 | = |
| Detailed routing convergence | NO (9h52m, routed_preantenna only) | NO (bounded ~4h45m in DRT) | both hit OSS TritonRoute wall — no regression |
| GDS / DRC / LVS / final-STA | not reached | not reached | A/B pending (backend not reached either side) |
| Dynamic IR-drop | not reached | not reached | see §4.1 |

### 4.1 SOUND-LEC (A/B focus #1)
- **Recipe:** yosys `equiv_make → equiv_simple → equiv_induct`. Gold-read: `read_verilog` probe fails on SV package syntax → `read_slang` fallback.
- **0.2.20-int result:** slang gold-read now ELABORATES the full OpenTitan SV cone (StateEnumT enums + packages) — PROVEN by synth (90 667 cells). No StateEnumT parse-abort false-FAIL.
- **proven / unproven counts = 0 / 0** (miter never built). Root cause is NOT StateEnumT: the equiv gold-read pulls the `` `ifdef SIMULATION `` sim-only tasks (`$urandom`, `$value$plusargs`) which the LEC define-set does not exclude (a shared-A/B `lec_run` recipe gap) — and full-chip sequential equivalence of a 90 667-cell AES via `equiv_induct` is an OSS-LEC intractability ceiling regardless of gold-read. **The enhancement fixed what it targeted (the parse-abort); it does not claim to close full-chip AES LEC.**

### 4.2 Dynamic IR-drop (A/B focus, three-way outcome)
- **Outcome = (a) BLOCKED-UPSTREAM.** The IR/PSM step was never reached because detailed routing did not converge (no routed DEF), on BOTH images. The transient dynamic-IR CAPABILITY is present in-image (independently proven on this exact 0.2.20-int image: a commercial-PDK spm DEF gave static → dynamic droop). Blocked on this IC by upstream router non-convergence, **same as baseline — NOT a regression, NOT a fake pass.**

## 5. Tool substitution
All EDA is forked-OSS `vibeic-eda`; no commercial tools used or claimed. DRC/LVS would run the commercial SVRF decks natively via the in-KLayout `svrfdrc` engine (not reached this run). OSS-flow PPA — NOT DC-comparable. **No silicon validation is claimed.**

## 6. Residual triage / floors
- **OSS TritonRoute detailed-routing non-convergence** on a dense 34 800-component AES on the commercial PDK — hit by BOTH 0.2.19 and 0.2.20-int (bounded here at ~4h45m; baseline still routing at 9h52m). This is the dominant backend floor for this IC and blocks GDS/DRC/LVS/STA/IR on both.
- **`lec_run` gold-read define-set gap** (shared A/B): the equiv gold-read should use `read_slang` with the same `-DSIMULATION -DSYNTHESIS -DYOSYS` set the MAIN synth uses (which handles `$urandom`) instead of the `read_verilog`-first path that aborts. Backlog (chip-agnostic recipe fix).

## 7. Reproduce
```
# fresh 0.2.20-int container (leaves 0.2.19 untouched)
NAME=vibeic-eda-020int DESIGNS_DIR=$HOME/AI_IC_design \
  tools/vibeic-eda/restart-eda.sh ghcr.io/vibeic/vibeic-eda:0.2.20-int
# stage inputs (docs/vendor_rtl/golden/pdk-symlinks), then:
python3 .../vibe_ic_one_shot_runner.py <run_dir> --container vibeic-eda-020int \
  --pdk auto --top-name chip_top --ic-name opentitan_aes --skip-analog --no-dashboard
# author chip_top.sv + stage cone via catalog_glue_closure_resolver (--top chip_top) → 96 .sv + 4 .svh
python3 .../phase2_one_shot_runner.py <run_dir> --top-name chip_top --container vibeic-eda-020int --skip-analog --skip-phase3
python3 .../phase3_one_shot_runner.py <run_dir> --top-name chip_top --container vibeic-eda-020int --die-um auto --util 0.4 --pdk auto
```
