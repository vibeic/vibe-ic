# Step 19 — Post-CTS Hold

## What ran
Re-stated OUR post-CTS/post-route hold cleanliness from PnR `openroad.log`
(resizer hold-repair pass), confirmed by the independent multi-corner STA in
step_22 (min-path hold slack), and the `eco/no_eco_summary.json` verdict.
Compared REF hold slack.

## Metrics side-by-side
| metric | OURS | REF |
|---|---|---|
| OpenROAD resizer hold | `[RSZ-0033] No hold violations found.` | `[RSZ-0033] No hold violations found.` |
| Hold slack SS (mcorner STA, SPEF) | +0.95 ns (MET) | +0.89 ns (MET) |
| Hold slack TT | +0.49 ns (MET) | +0.46 ns (MET) |
| Hold slack FF | +0.30 ns (MET) | +0.30 ns (MET) |
| ECO needed | no (wns_negative=false, tns_zero=true) | no (same) |

## Verdict: BOTH-CLEAN
OURS is hold-clean (resizer reports no hold violations; min-path slack positive
at every corner). REF is identically hold-clean. The FF corner (fastest, tightest
hold) gives +0.30 ns on both — essentially the same hold margin. No ECO needed
on either side.
