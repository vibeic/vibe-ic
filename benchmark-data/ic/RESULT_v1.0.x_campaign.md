# Benchmark-IC campaign — plugin v1.0.x (2026-06-14)

Benchmark Agent close-loop campaign on the 6 canonical ICs. Clean-room (input docs only,
golden = cross-check oracle only). Non-destructive: this is the v1.0.x campaign summary; the
per-IC canonical reports (benchmark-data/ic/<ic>/BENCHMARK_VERIFICATION_REPORT.md, RESULT.md)
are NOT overwritten (this run is a mid-close-loop deeper-layer sweep, not a converged six-pillar
re-verification).

## Roster
ibex (REUSED-IP CPU) · opentitan_aes (REUSED-IP crypto) · sha256 · spm · subservient · u_hawaii_adc

## Close-loop outcome (capture → Core-Agent fix → field-verify)
- **Round-1 (v1.0.0 → v1.0.22): 21 chip-agnostic plugin gaps (#605-#625) captured → Core Agent fixed all → field-verified 21/21 ADEQUATE, 0 reopen.** Each fix carries positive + §4.05 negative-no-leak.
  - Wave-2 doc→GDS: **spm reached a real 444 MB GDSII (signoff DRC = 0 violations, LVS "circuits match uniquely", post-route STA MET); subservient reached a real 486 MB DRC-clean GDSII.**
- **Round-2 (v1.0.22 clean-room re-run): 0 regressions (all 21 round-1 fixes hold) + 15 deeper-layer gaps (#627-#641).** Field-verified 14/15 ADEQUATE; #627 + #634 reopened as partial fixes (precise line-level counter-evidence filed; Core-Agent re-fix pending).
  - Gap trajectory **21 → 15** (declining; deeper layer: Phase-1 extraction fidelity, gate class-awareness, REUSED-IP dependency closure, analog-track gating, CDC evidence parsing, RTL top-port header parsing).

## Per-IC deepest step reached (round-2, --skip-phase3 Wave-1)
| IC | deepest | phase-2 verdict |
|---|---|---|
| sha256 | Step 9 synth (9.1k cells) | PASS_WITH_WAIVERS |
| spm | Step 9 synth (304 cells) | (Phase-2 clean; round-1 Wave-2 → full GDS) |
| subservient | Step 9 synth (4000 cells) | PASS_WITH_WAIVERS |
| u_hawaii_adc | Step 9 synth (now data_converter class) | (mixed-signal; analog track separate) |
| opentitan_aes | Step 9 synth (yosys-slang) | (REUSED-IP closure) |
| ibex | Step 9 synth (17.6k cells) | (REUSED-IP) |

## Verification discipline
- Field-verify against PINNED commit worktrees (race-safe vs the Core Agent's live tree), positive + #4.05 negative-no-leak on every fix.
- Adversarial candidate verification dropped ~35% of self-reported residuals (non-reproducing / dedup / designed AI-fallback boundary) before filing — no hallucinated/duplicate backlog.

## Status
NOT yet converged (round-2 surfaced 15 deeper-layer gaps; #627/#634 re-fix pending). Loop is sound:
0 regressions, declining gap count, deeper reach each round. Next: Core-Agent re-fix #627/#634 →
6-IC round-3 clean-room re-run.

_Backlog: reyerchu/AI_IC_design issues #605-#642 (organic-backlog). Campaign trail: AI_IC_design/_bench6_v100_r1, _bench6_v100_r2._
