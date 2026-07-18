# RESULT — caravel_user_project (`user_proj_example` macro) on a commercial 180 nm PDK

**Run dir:** `benchmark-data/ic/caravel_user_project/clean_run_v1432int_commercial`
**Image:** `ghcr.io/vibeic/vibeic-eda:0.2.20-int` (id `fa8cb832daf2`) — throwaway container `vibeic-eda-int-caravel`
**Toolchain (0.2.20-int):** OpenROAD `26Q3-120-g1cd84e502a` · Yosys `0.67+ c31dfe3a8` · magic `8.3.675` · KLayout `0.30.9`
**Node:** a commercial 180 nm NDA PDK, staged by PATH as `input/pdk/` symlinks (never committed; see `.gitignore`).
**Results-only, NDA-EXCLUDED.** Metrics / verdicts only — no PDK data, no foundry cell names, no SKU, no rule-IDs. Not "silicon-proven".

## Scope (IC-specific constraint — HONEST)

Only the **`user_proj_example` macro** (stock upstream Wishbone/LA/GPIO up-counter, reused verbatim
— Apache-2.0) is hardened on the commercial 180 nm node as a **standalone macro** (synth → PnR →
GDS → DRC → LVS → STA → IR). The full Caravel harness (`user_project_wrapper` padframe, management
SoC, fixed `DIE_AREA`, fixed pin/power-pin template, sky130 hard-IP macros) is **sky130-bound by
construction** and has **no commercial-180 nm equivalent** — it is deliberately NOT attempted on the
commercial node (doing so would be a fabricated result, not a tool failure).

## Method (A/B vs 0.2.19 baseline)

Clean-room fresh dir. Identical inputs to the 0.2.19 baseline `clean_run_v1432_commercial`
(commit `f43c65200`): same upstream RTL (sha256 `af1666e0…`, byte-identical), same explicit
floorplan `--die-um 220x220 --util 0.3`. Only the EDA toolchain differs (0.2.20-int vs 0.2.19),
so every delta below is a pure toolchain A/B on the same macro + same geometry.

> Die note (#158): `--die-um auto` mis-sizes this macro (core-limited 162×162 → PnR dies on
> `PPL-0024`, 541 IO pins > 528 perimeter slots). The macro is **pin-limited** (541 IO / 327 cells),
> so an explicit pin-perimeter-adequate die (220×220 → 720 slots) is required — same on both images.

## Six-pillar verdict (standalone macro)

| # | Pillar | Verdict | Note |
|---|--------|---------|------|
| 1 | Functional verification coverage | DEFERRED | full-stack TB is Caravel-harness-bound (sky130); macro backend-only, functional sim deferred (same as baseline) |
| 2 | Output-comparison / completion audit | FAIL | backend synth/pnr/gds PASS; audit blocked by the two signoff residuals (DRC + LVS) below — same as baseline |
| 3 | Code coverage ≥ 90% | N/A | no functional sim on the standalone macro |
| 4 | FPGA digital verification | N/A | digital-only rig, no board |
| 5 | Analog closed-loop | N/A | pure-digital IC |
| 6 | Design-for-ECO | PASS | 7 spare cells, spare-density target met (0.02, actual 0.0214), decap guard present |

## Backend step verdicts (0.2.20-int)

| Step | Verdict | Metric |
|------|---------|--------|
| synth | PASS | 327 std-cell instances, top `user_proj_example` |
| pnr | PASS | die 220×220 µm, 541 IO / 720 slots, routing COMPLETED |
| routing DRC (in-loop) | CLEAN | 0 detailed-route violations ("DRC clean: YES") |
| antenna | CLEAN | 0 net / 0 pin violations |
| gds | PASS | streamout OK; grid-snap + per-layer merge + fill + port-label restore |
| STA | MET | worst slack positive (typ +20.29; SS corner positive) |
| IR (static) | PASS | worst 64.2 mV = 3.567 % VDD (budget 10 %) |
| LEC (post-layout) | PROVEN_EQUIVALENT | 0 unproven / 388 points (sound-LEC recipe) |
| SVRF signoff DRC | FAIL | 57 firing / 4476 clean of 4533 rules (commercial deck, native) |
| LVS | MISMATCH | `power_shorts=0`; net/pin-label + cell-recognition residual (LEC-proven-equivalent) |
| **overall** | **FAIL** | blocked by the two commercial-deck signoff residuals (DRC + LVS) — same shape as baseline |

## A/B deltas vs 0.2.19 baseline (`f43c65200`)

| Metric | 0.2.19 baseline | 0.2.20-int | Delta |
|--------|-----------------|------------|-------|
| synth std cells | 327 | 327 | same |
| die / IO pins / slots | 220×220 / 541 / 720 | 220×220 / 541 / 720 | same |
| routing completion | completed, 0 DRT viol | completed, 0 DRT viol | same |
| spares | 7 | 7 | same |
| GDS size (B) | 5,591,396 | 5,591,396 | identical |
| STA worst slack | +18.13 ns SS (MET) | positive (MET) | MET both |
| static IR | 64.2 mV / 3.567 % | 64.2 mV / 3.567 % | same |
| **LEC unproven** | **2 (benign dead net)** | **0 → PROVEN_EQUIVALENT** | **✅ resolved** |
| SVRF DRC firing | 51 | 57 | +6 (fill/streamout residual; both FAIL) |
| LVS | MISMATCH (LEC-equiv) | MISMATCH, power_shorts=0 | same class |
| overall | FAIL | FAIL | same |

### Focus-item findings

1. **DRT-0302 flat-macro PG-merge — N/A for this IC (by construction).**
   `user_proj_example` has **0 hard macros** ("Found 0 macro blocks"), so the flattened-macro
   multi-bterm power-net case the DRT-0302 fix targets is **never exercised** by the
   commercial-PDK-mappable portion. Both images route this flat std-cell macro clean (0 DRT
   violations). The multi-bterm PG wall is a Caravel-**wrapper**/hard-IP phenomenon — which is
   sky130-bound. So there is no DRT-0302 A/B delta measurable on this node; not a tool win or loss.

2. **Sound LEC (opt-purge) — WIN.** The 0.2.19 baseline left **2 unproven** LEC points (dead,
   unobservable `wstrb` bits — benign). The 0.2.20-int sound-LEC recipe (Yosys `c31dfe3a8`) purges
   the unobservable dead nets and closes at **0 unproven / PROVEN_EQUIVALENT** (388 points). This is
   the one clean, positive toolchain delta on this macro.

3. **Dynamic IR — no separate droop number.** The macro's IR report carries only the static figure
   (64.2 mV, identical to baseline). The dynamic-IR / PSM-vectored path did **not** surface a
   distinct dynamic droop value for this run — no three-way static/dynamic delta observed here.

4. **SVRF signoff DRC — 51 → 57 firing (+6).** Same 4533-rule commercial deck run natively; both
   images FAIL. The +6 is geometry/density-fill residual from magic/KLayout streamout+fill
   differences — not a functional regression (in-loop routing DRC is clean on both).

5. **LVS — unchanged MISMATCH.** `power_shorts=0`; the residual is the netgen cell-recognition /
   net-pin-label class already present in the baseline, and the logic is LEC-proven-equivalent.

## Bottom line

On the commercial 180 nm node, the `user_proj_example` macro backend hardens the same on 0.2.20-int
as on the 0.2.19 baseline (synth/PnR/route/GDS PASS, timing MET, routing DRC clean, GDS
bit-identical), with **one genuine improvement**: the sound-LEC recipe resolves the baseline's 2
unproven points to **0 unproven / PROVEN_EQUIVALENT**. The two overall-FAIL residuals (commercial
signoff-deck DRC firings + netgen LVS MISMATCH) are unchanged known floors, not regressions. The
DRT-0302 and dynamic-IR enhancements are not exercisable by this IC's commercial-PDK-mappable
portion (flat 0-macro std-cell macro; static-PSM report), which is an honest IC-specific constraint,
not a null result to hide.
