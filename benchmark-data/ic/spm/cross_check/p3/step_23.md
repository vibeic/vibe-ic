# Step 23 — Post-route STA (SS / TT / FF)

## What ran
Re-ran multi-corner post-route STA on OURS in the iic-eda container with OpenSTA:
routed netlist `spm_pnr.v` + `constraint.sdc` (20 ns / 50 MHz) + the OpenRCX
SPEF (`spm_xc.spef`, from step_21) back-annotated at SS/TT/FF.
TCL: `phase3/stage3/sta/mcorner_xc.tcl`, log `mcorner_xc.log`.
Same flow re-run on REF (`mcorner_ref_xc.tcl`).

## Metrics side-by-side (worst slack, SPEF-annotated)
| corner | OUR setup | OUR hold | REF setup | REF hold |
|---|---|---|---|---|
| SS (ss_100C_1v60) | +6.61 ns MET | +0.95 ns MET | +16.87 ns MET | +0.89 ns MET |
| TT (tt_025C_1v80) | +12.41 ns MET | +0.49 ns MET | +17.42 ns MET | +0.46 ns MET |
| FF (ff_n40C_1v95) | +14.59 ns MET | +0.30 ns MET | +17.63 ns MET | +0.30 ns MET |

Canonical single-corner post-route reports also MET:
- OURS `post_route_timing.rpt`: slack +13.01 ns (input→FF path, tt).
- REF `post_route_timing.rpt`: +17.44 ns; REF `post_spef_timing.rpt`: +17.49 ns.

## Note on the "+6.99/+7.49/+7.68" figures
The orchestrator-quoted SS/TT/FF (+6.99/+7.49/+7.68 ns) were measured with a
`set_wire_rc` estimate (no SPEF). With the real OpenRCX SPEF back-annotated the
worst SS setup is +6.61 ns — slightly tighter (SPEF adds real net RC) but the
same order and still comfortably positive.

## Verdict: BOTH-CLEAN (all corners MET)
Both designs close timing at every PVT corner with positive setup AND hold slack.
OUR setup margin is smaller than REF (SS +6.61 vs +16.87 ns) because the
carry-save adder has a longer combinational ripple chain (the critical path is a
~20-stage o311a/o31a/xor cascade visible in `post_route_timing.rpt`), whereas the
REF shift-add path is FF→port. This is the expected micro-architecture difference,
not a failure — OURS still has > 6 ns slack at the worst corner on a 20 ns clock.
Hold margins are essentially identical (FF +0.30 ns both).
