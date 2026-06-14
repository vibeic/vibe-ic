# caravel_user_project — Benchmark IC #7 — Round-6 RESULT (reconstructed from disk)

> The round-6 benchmark-agent hit a session limit and was cut off before writing
> its own RESULT. This file is reconstructed by the orchestrator directly from the
> committed run artifacts under `caravel_r6/`.

- **Plugin under test:** PUBLIC tree v1.0.47 (`/home/reyerchu/vibe-ic/...`).
- **Project:** `_bench7_caravel_v1034_cleanroom/caravel_r6` (fresh clean-room, input-only seed).
- **Shape:** A/D (full runner, SoC integration).

## Milestone: the chain reached Phase-3 GDS for the first time
`reports/orchestrator/vibe_ic_one_shot.json`:
- phase1 = SKIPPED (rc 0, already done), **phase2 = PASS_WITH_WAIVERS (rc 0)**, analog = SKIPPED, **phase3 = FAIL**, halted_at = phase3.

`reports/orchestrator/phase3_one_shot.json` per-step:
| Step | Status | Note |
|---|---|---|
| synth | PASS | user_project_wrapper_synth.v |
| pnr | PASS | DEF COMPONENTS=940896; spares=7; via_audit skipped (techlef path) |
| gds | PASS | user_project_wrapper.gds = **2,074,657,830 bytes (~2GB)**; streamout=klayout (#600/#601) |
| drc | **PASS** | violations=0 |
| lvs | **FAIL** | netgen mismatch (#443); pin mismatch io_out[N] ↔ la_data_out[N] |
| canonicalize_artefacts | PASS | 41 canonical artefacts; STA basis discrepancy note |

## Per-fix field verdicts (this run)
- **#675 (formal Step-5 deferral) — RESOLVED.** phase2 = PASS_WITH_WAIVERS, halted_at=phase3 — the chain cleared phase2 and drove into Phase 3. Step 5 is the disclosed deferral, no longer a blocker.
- **#676 (phantom POR analog) — RESOLVED.** analog SKIPPED (digital IC), no phantom `por` block; P0 passed.
- **#677 (typed-field floors) — RESOLVED.** `l_doc_structured_field_count_check` = PASS.
- #650 (pin_order) / #651 (signoff PASS_WITH_WAIVERS): signoff not reached (LVS halts first); #651 promotion mechanism already confirmed firing at Step 4 in round-5.

## NEW Phase-3 backend findings (under adversarial characterization → filing)
1. **Fill/decap explosion (ROOT):** DEF has 940,896 COMPONENTS (~5000× the ~189-cell counter) → ~2GB GDS (known-good = 2.8MB). Likely full-density fill/decap over the entire empty 2920×3520µm fixed caravel die.
2. **LVS pin mismatch:** netgen FAIL, `io_out[N]` ↔ `la_data_out[N]` — connectivity/labeling, under investigation (plugin vs design).
3. **flow_compliance_check hang:** the SOLE-ACCEPTANCE program hangs (>240s, pure-python) on the 2GB GDS — acceptance-gate robustness gap (likely downstream of #1).
4. **via_audit techlef path:** `sky130_fd_sc_hd__nom.tlef` not found — under triage (env-only vs path-resolution bug).

Findings 1-4 are being root-caused + adversarially verified (root vs symptom, plugin vs env) before filing as chip-AGNOSTIC ORGANIC issues.

## Convergence status
**NOT converged.** #675/#676/#677 field-verified RESOLVED; the chain advanced from "blocked at Step 5"
(round-5) to "**phase2 PASS_WITH_WAIVERS, phase3 synth→pnr→gds→drc PASS, halt at LVS**" (round-6) —
the deepest reach yet. New Phase-3 backend gaps (fill explosion / LVS mismatch / acceptance-gate
hang) are the next loop iteration.
