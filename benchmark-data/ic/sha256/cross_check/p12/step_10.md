# Step 10 — Pre-layout STA multi-corner on OUR netlist @ 25.9 ns

**Verdict: DIFFERENT-BUT-OK** (setup VIOLATED pre-layout at all corners — same as REF pre-PnR; hold clean; REF closes tt/ff only post-PnR)

## What ran
OpenSTA 3.1.0 on OUR synthesized netlist (`synth/ours_netlist.v`,
dfflibmap+abc, 1584 DFF) with `sha256.sdc` (clk 25.9 ns, IO 2.0 ns), three
corners using the local sky130_fd_sc_hd libs:
- tt_025C_1v80, ss_100C_1v60, ff_n40C_1v95.

## Result (OUR pre-layout)
| Corner | Setup WNS | Setup TNS | Hold worst | 
|--------|-----------|-----------|------------|
| tt | -35.72 ns (VIOLATED) | -20360 | +0.41 ns (MET) |
| ss | -85.82 ns (VIOLATED) | -53686 | +0.85 ns (MET) |
| ff | -15.45 ns (VIOLATED) | -7335 | +0.26 ns (MET) |

Critical path is FF→FF inside the round datapath (the modular-add network), as
expected. Hold passes at all corners.

## REF comparison (HONEST — not apples-to-apples)
- REF **pre_pnr_timing.rpt**: setup slack **-83.42 ns (VIOLATED)** at 20 ns —
  i.e. REF's raw pre-layout netlist is equally setup-violated. So OUR pre-layout
  result is **in parity** with REF pre-layout.
- REF **post-route multicorner** (after PnR+CTS+sizing): setup_tt **+6.59 MET**,
  setup_ff **+41.83 MET**, setup_ss **-94 VIOLATED**. REF only closes timing
  after the backend, and even then ss stays violated.

## Finding
At the **pre-layout** stage both designs show large setup violations on the
round path — this is expected for an unbuffered, unplaced, ABC-mapped netlist
with default wire-loads (no drive sizing, no clock tree). OUR numbers are the
same order of magnitude as REF's pre-PnR (-35 vs -83 ns). Closing timing is a
Phase-3 (PnR) activity, out of scope for this P1/2 cross-check. Hold is clean in
both. Verdict DIFFERENT-BUT-OK: matches REF pre-layout behaviour; deferred to
PnR for sign-off, exactly as REF did.
