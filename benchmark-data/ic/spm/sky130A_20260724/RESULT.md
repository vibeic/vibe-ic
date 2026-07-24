# RESULT — spm × sky130A (Benchmark IC campaign, plugin v1.5.65, 2026-07-24)

_Run date: 2026-07-24. IC: `spm` — configurable N-bit serial-parallel integer
multiplier (N=32), PDK: sky130A (`sky130_fd_sc_hd`). Plugin: v1.5.65.
Container: `vibeic-eda:0.2.28`. This supersedes-by-addition, not by
overwrite, the earlier `../RESULT.md` (2026-05-26, plugin v1.4.6x era) — kept
as a separate dated record so neither claim is silently conflated with the
other; both are independently reproducible from their own artifacts._

## VERDICT

**PASS_WITH_WAIVERS.** Independently re-derived from raw artifacts:

- **GDS**: `spm.gds`, 730,458 bytes, present at `phase3/stage4/gds/spm.gds`.
- **Sign-off DRC** (KLayout): raw report — empty `<items>` list, **0
  violations**.
- **LVS** (netgen): raw report tail — *"Cell pin lists are equivalent. Device
  classes spm and spm are equivalent. Final result: **Circuits match
  uniquely**."*
- **STA** (multi-corner, real SPEF): raw report — worst setup slack **+4.56
  ns** (TNS 0.00), worst hold slack **+0.33 ns** (TNS 0.00). Both MET.
- Confirmed via `flow_compliance_check.py --strict` against the run
  directory: **Overall: PASS_WITH_WAIVERS**.

This run also validates the fleet-wide fix landed the same day: an earlier
PnR repair-escalation change (`step_signoff_drv_wire_length_repair`,
v1.5.64) was found to regress a different cell (caravel_user_project ×
sky130A) and was disabled (v1.5.65, plugin repo commit `e9de8601`). This
spm × sky130A run is on the POST-revert plugin — its clean STA margins
(+4.56 / +0.33 ns) confirm the revert did not lose the smaller, real
improvement from the earlier bounded repair-design loop (v1.5.61).

## Honest scope

One cell (IC × PDK) of the open-PDK matrix. See
`benchmark-data/BENCHMARK_IC_CAMPAIGN_STATUS.md` for the full matrix's
current per-cell status. Nothing here is claimed for any cell other than
`spm × sky130A` on this specific plugin version.
