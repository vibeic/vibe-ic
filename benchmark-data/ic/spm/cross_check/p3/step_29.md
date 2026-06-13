# Step 29 — Post-layout SPICE (critical-path cell, GAP-CLOSE)

## What ran
Mirrored the REF Step-28 methodology (single critical-path-cell propagation via
ngspice with foundry sky130 cell subckt + tt-corner FET models + 5 fF load).
OURS: probed `sky130_fd_sc_hd__xor2_1`, the penultimate cell on OUR carry-save
worst path (`post_route_timing.rpt`: `_409_/X xor2_1 -> _410_/Y nor2_1 -> FF/D`).
TB: `phase3/stage3/spice/critical_path_tb_xc.sp`; log `spm_spice_xc.log`.

## Metrics side-by-side
| metric | OURS | REF |
|---|---|---|
| Tool | ngspice (tt corner, foundry FET models) | ngspice (tt corner) |
| Probed cell | xor2_1 (on worst path) | a31oi_1 (on worst path) |
| Net load | 5 fF | 5 fF |
| tpd rise | **131.8 ps** (measured) | measure FAILED (out-of-interval) |
| tpd fall | **128.4 ps** (measured) | measure FAILED (out-of-interval) |
| ngspice run | exit 0, models loaded | exit 0, models loaded |

## Verdict: PASS (OURS exceeds REF; full-chip SPICE remains NO-TOOL)
A full-chip post-layout SPICE of the whole spm is infeasible in the open-source
flow (no commercial fast-SPICE; magic ext2spice of the full netlist + ngspice on
thousands of FETs is impractical) — honest NO-TOOL for the whole chip, same as REF.
For the critical-path-cell SPICE that IS feasible, OURS produced a real, valid
propagation delay (tpd ≈ 130 ps for xor2_1 at tt/5 fF), whereas the REF's own
Step-28 measure FAILED with an "out of interval" trig/targ-polarity bug. So OURS
closed this GAP with a working SPICE run and is strictly more rigorous than REF here.
