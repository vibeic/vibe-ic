# Step 25 — Antenna Check (GAP-CLOSE)

## What ran
OpenROAD `check_antennas` on OUR routed.def in the iic-eda container.
TCL: `phase3/stage3/pnr/antenna_xc.tcl`; report `antenna_xc.rpt`; log
`antenna_xc.log`.

## Metrics side-by-side
| metric | OURS | REF |
|---|---|---|
| Tool | openroad check_antennas | openroad check_antennas |
| Net violations (ANT-0002) | 0 | 0 |
| Pin violations (ANT-0001) | 0 | 0 |
| Diode insertions | none needed | none needed |
| Sign-off | PASS | PASS |

## Verdict: BOTH-CLEAN (GAP closed)
`check_antennas` found 0 net and 0 pin antenna (gate-oxide) violations on OURS,
matching the REF 0/0. Both are small single-clock designs whose detailed router
satisfied the sky130 antenna ratio rules without any diode insertions. Antenna
GAP for OURS now closed with a real OpenROAD run.
