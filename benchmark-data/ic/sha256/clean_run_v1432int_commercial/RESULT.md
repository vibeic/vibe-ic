# sha256 — real-node A/B re-verify on 0.2.20-int (RESULT)

- **Run dir:** `benchmark-data/ic/sha256/clean_run_v1432int_commercial/`
- **Purpose:** A/B validation of the forked-EDA enhancements in `ghcr.io/vibeic/vibeic-eda:0.2.20-int` (image id `fa8cb832daf2`) vs the `0.2.19` baseline, on a **commercial 180 nm PDK (NDA)** digital sign-off path. The single controlled variable is the EDA image.
- **EDA image:** `ghcr.io/vibeic/vibeic-eda:0.2.20-int` — fresh throwaway container; the live baseline container was left untouched. In-image forks under test: OpenROAD (transient/dynamic IR + PSM vectored + PEX + DRT), yosys (sound LEC + ICG), magic (zero-width LVS), iverilog.
- **PDK:** commercial 180 nm, provided under NDA — staged out-of-git, symlinked into `input/pdk/`, `.gitignore` excludes it. This results tree contains **numbers only** — no device / cell / rule / model tokens. Not silicon-proven; OSS-flow, not commercial-tool cross-validated.
- **Date:** 2026-07-18.
- **§4.1 clean-room:** fresh run dir, `input/docs/` (L1-L9) only.
- **Method (backend A/B):** the design-under-test RTL is the **identical NIST-verified SHA-256/224 DUT** from the 0.2.19 baseline (authored-from-docs, image-independent; md5 byte-match), re-seeded so synth/LEC/PnR/DRC/LVS/IR/timing differ **only** by the EDA image. This isolates the enhancement effect from any RTL-authoring confound.

---

## 1. Headline

- **Scope of this run: PARTIAL.** The flow was **wound down at the owner's request before Phase 3 completed** (to quiesce the tree for a push + rebuild / NDA clean-pass). Phase 1 and Phase 2 ran to completion on 0.2.20-int; Phase 3 (PnR → GDS → DRC → LVS → STA → IR) was entered but **terminated as PnR began** — no Phase-3 sign-off artifacts were produced this run. The Phase-3-focused A/B items (dynamic IR, post-route timing, LVS, DRC, post-layout LEC) are therefore **NOT MEASURED here**; the baseline numbers below are carried as last-known reference and the enhancement status is reported honestly.
- **Functional DUT = PASS on 0.2.20-int.** The enhanced iverilog compiled + ran the NIST FIPS-180-4 self-verify: **all 6 vectors match, 0 mismatch** (SHA-256 & SHA-224 × {abc, empty, 2-block} + the unallocated-address error flag).
- **Phase 1 = PASS** (24/24 L-docs, 100 % coverage; class `crypto_accelerator`).
- **Phase 2 synth = PASS** on the enhanced yosys; the mapped netlist is **near-identical** to the baseline (size Δ ≈ +252 B on ~2.26 MB), i.e. no material synthesis divergence from the ICG/sound-LEC fork at this design.
- **Phase 2 Step-13 LEC (RTL ≡ synth) = SKIPPED-CONDITION (timeout)** — **same as baseline.** This is a large-crypto equivalence **scaling** timeout (the checker exceeds its wall budget), which is orthogonal to what the sound-LEC fork addresses (soundness, i.e. never falsely proving); no A/B change at this checkpoint on this IC.

---

## 2. Shape / entry point

- **Shape A — full runner.** Entry: `vibe_ic_one_shot_runner.py <run_dir> --ic-name sha256 --pdk auto --no-dashboard --container <throwaway-0.2.20-int>` — identical invocation to the baseline one-shot except the container image. `--pdk auto` detected `input/pdk/{liberty,lef}` → `custom:pdk`.
- Plugin at HEAD (`d47799bed`). DUT RTL pre-seeded (image-independent) so Phase 2 proceeded to synth without re-authoring.

## 3. A/B scorecard

| Dimension | Baseline (0.2.19) | This run (0.2.20-int) | A/B disposition |
|---|---|---|---|
| Functional (iverilog, NIST FIPS-180-4) | 6/6 match, 0 mismatch | **6/6 match, 0 mismatch** | PARITY — enhanced iverilog verifies the DUT |
| Phase 1 (docs → L1-L23) | PASS 24/24, 100 % | **PASS 24/24, 100 %** | PARITY |
| Phase 2 synth (yosys) | PASS (~2.26 MB netlist) | **PASS (~2.26 MB, Δ+252 B)** | PARITY — no material ICG divergence |
| Phase 2 Step-13 LEC (RTL≡synth) | SKIPPED-CONDITION (timeout 1200 s) | **SKIPPED-CONDITION (timeout)** | PARITY — scaling timeout, orthogonal to sound-LEC soundness |
| **Dynamic transient IR** | BLOCKED — `ERROR_NO_PSM_IR` (upstream OpenROAD STA-0164 parsing the PDK bridge SPICE .lib → PSM emitted no transient drop). Static IR: 55.7 mV = 3.094 % VDD (budget 10 %) PASS | **NOT MEASURED** (phase 3 not reached) | Deferred. Transient **capability** is present in-image (independently proven elsewhere on the same image: static→dynamic droop emitted on a commercial-PDK block). Whether THIS IC's flow clears the STA-0164 .lib-parse upstream block is unproven this run. |
| **Post-route timing** (worst setup) | setup WNS −41.1 ns (multi-corner OCV, slow corner); SPEF-based −12.46 ns; achievable Fmax 14.924 MHz vs 38.6 MHz spec; post-ECO −23.07 ns (real floor); hold +0.21 ns MET | **NOT MEASURED** (phase 3 not reached) | Deferred — no post-route STA produced this run |
| **LVS** (KLayout-native) | FAIL — extraction produced no netlist, rc=124 **TIMEOUT (~24 h)** | **NOT MEASURED** (phase 3 not reached) | Deferred. Bound is in place at HEAD: extraction runs under a 1800 s (30-min) per-call cap + container-side hard kill → the 24 h hang cannot recur; whether magic zero-width extraction now converges under the cap is unproven this run. |
| **DRC** (native SVRF) | FAIL — 4497 clean / 36 firing / 0 skipped | **NOT MEASURED** (phase 3 not reached) | Deferred |
| Post-layout LEC (synth≡pnr) | PROVEN_EQUIVALENT (9231 proven / 0 unproven) | **NOT MEASURED** (phase 3 not reached) | Deferred |

## 4. Disposition

- **What this run establishes on 0.2.20-int:** the front of the flow — enhanced iverilog functional sign-off, Phase-1 ingestion, and enhanced-yosys synth — is at **parity** with the baseline on the identical DUT; nothing regressed. The Phase-2 Step-13 RTL≡synth LEC remains an honest SKIPPED-CONDITION (a scaling timeout, not a false pass).
- **What this run does NOT establish:** the Phase-3 enhancement A/B (dynamic transient IR, post-route timing after the DRT/repair fork, KLayout-native LVS after magic zero-width, native-SVRF DRC, post-layout LEC). Phase 3 was intentionally not completed — the run was wound down as PnR started. These require a full Phase-3 completion on 0.2.20-int and remain open.
- **No fabricated closure:** no Phase-3 verdict is claimed from a step that did not run.

## 5. Reproduce

```bash
PLUGIN=/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic          # HEAD d47799bed
RUN=/home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1432int_commercial
# commercial 180 nm PDK staged out-of-git, symlinked into input/pdk/{liberty,lef,gds,calibre,spice,bridge}; input/pdk/ gitignored.
# fresh throwaway container off the 0.2.20-int image (identity /home mount), distinct name:
docker run -d --name <throwaway> -v /home/reyerchu:/home/reyerchu -v /home/reyerchu/AI_IC_design:/foss/designs \
  --user 1000 ghcr.io/vibeic/vibeic-eda:0.2.20-int --skip sleep infinity
python3 $PLUGIN/programs/vibe_ic_one_shot_runner.py $RUN --ic-name sha256 --pdk auto --no-dashboard --container <throwaway>
# functional self-verify (public NIST FIPS-180-4 vectors):
cd $RUN/_selfverify && iverilog -g2012 -o sim_nist tb_sha256_nist.v ../phase2/stage1/rtl/sha256.v && vvp sim_nist
```
Input: `input/docs/L1-L9` (design INPUT only). Image id `fa8cb832daf2`.
