# SOURCE_MANIFEST — caravel_user_project (7th benchmark IC)

- **Upstream:** https://github.com/chipfoundry/caravel_user_project (Apache-2.0),
  stock `user_proj_example` (a Wishbone/LA/GPIO-controllable counter) wrapped in the
  Caravel `user_project_wrapper`. Target PDK: **SKY130A**.
- **Joins** the bench6 set: ibex / opentitan_aes / sha256 / spm / subservient / u_hawaii_adc.
- **Shape:** A/D (full runner, SoC integration) — driven through
  `vibe_ic_one_shot_runner.py` (NOT a hand-rolled harness).

## What's in this directory
The **converged run** (clean-room round 11) per-step outputs, mirroring the bench6
convention: `input/ phase1/ phase2/ phase3/ reports/` + `RESULT.md`.
- `RESULT.md` — the converged round-11 result.
- `closeloop_history/` — the full `RESULT_r1..r11.md` trail + `CLEANROOM_MANIFEST.md`.

**Excluded (matches bench6):** heavy layout binaries — `*.gds *.def *.spef *.ext
*.mag *.vcd *.vvp`. They are reproducible from the committed RTL + configs via the
runner. (The converged GDSII was 89 MB; DRC 0-violations, LVS match-uniquely.)

## Convergence (2026-06-15, plugin v1.0.60)
Driven from RTL → GDSII → tapeout-checklist over 11 clean-room rounds. The close-loop
filed + fixed + **field-verified 23 chip-AGNOSTIC plugin gaps**:
`#643-648, #661-662, #673-677, #684-687, #691-694, #696, #698`
(plugin fixes shipped in this repo, vibeic/vibe-ic, v1.0.43 → v1.0.60).

**Final `flow_compliance_check --strict`:** 29/31 executed PASS, 3 DEFERRED. Full
physical chain GREEN: PnR(met1-met5) → CTS → hold-fix → SPEF → MCMM STA →
IR/EM/antenna/SI → PERC PASS → DRC 0-viol / LVS match-uniquely / ERC benign →
ECO → Power → Metal-Fill → DFM → Tapeout-checklist → GDSII 89 MB.

**Residual 2 FAILs are NOT plugin gaps** (genuine convergence floor):
- Step P0 `l_doc_structured_field_count_check` — phase1 L-doc typed-field-depth on
  sparse upstream docs (pre-existing, tracked under phase1 coverage).
- Step 38 `foundry_handoff_package_check` — foundry-handoff kit assembler not shipped
  (roadmap; needs commercial mask/WAT/scribe/corner-kit data).
Plus open-tool cap-gaps: FPGA board (no DE10/Quartus), SDF/SPICE post-layout (#430),
DFT/ATPG/LEC (#430), CDC (#433c), Formal (#608/#675).
