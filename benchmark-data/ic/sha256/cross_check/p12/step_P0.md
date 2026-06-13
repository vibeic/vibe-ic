# Step P0 — Structural checkers on OURS

**Verdict: PARTIAL-PASS / NO-TOOL for full 77-gate suite** (RTL-applicable checkers PASS; full project-tree P0 not runnable on bare RTL staging)

## What ran
The plugin P0 structural-checker family lives at
`/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/`
(413 programs). The MCP `eda_rtl_audit` wrapper FAILED — the container's expected
programs dir (`/home/user/AI_IC_design/vibe-ic-marketplace/plugins/vibe-ic-d/programs/`)
is **missing** (confirmed by `eda_doctor`: `[FAIL] plugin_programs_dir`). So the
checkers were run **directly with python3** against the host program copies.

## Result (OURS, RTL-applicable subset)
| Checker | OURS | REF |
|---------|------|-----|
| rtl_hygiene_lint | **0 err / 0 warn / 0 info** | 0 err / 1 WARN (mode_r unread) |
| oe_pattern_check | 0 OE signals (no tristate — correct for mem-mapped block) | — |

## Honest NO-TOOL note on the "77 structural checkers"
The full P0 acceptance gate (`eda_phase23_completion_audit`, 34 canonical
artefacts, and the ~77-checker structural suite) is designed to run against a
**complete project tree** (rtl/ + fpga/ + gds/ + synth/ + sta/ reports). Run
against the bare RTL **staging dir** (`_sha256_xc_p12/ours_rtl`), the vast
majority would be N/A or FAIL-by-absence (no GDS, no FPGA SOF, no PnR signoff in
the staging copy) — those belong to Phase-3, out of scope for a P1/2 RTL
cross-check. Running them against the *real* project
(`/home/reyerchu/vibe-ic/benchmark_clean/sha256/`) is the Phase-3 agent's job and
that tree was deliberately not touched.

→ The RTL-relevant structural checkers PASS on OURS (cleaner than REF). The full
77-/34-gate project-level P0 is recorded as **NO-TOOL here** (MCP programs dir
missing) + **out-of-scope** (needs full Phase-3 tree), not fabricated as a pass.
