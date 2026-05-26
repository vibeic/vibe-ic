# Step 19 — Post-CTS hold (both ≥ 0)

**What ran:** Read OURS OpenROAD `repair_timing -hold` result (RSZ-0033) and the 9-corner hold slacks; compared to REF multicorner hold reports.

| Corner | OURS worst hold slack (ns) | REF worst hold slack (ns) |
|---|---|---|
| Post-CTS hold-fix | "No hold violations found" (RSZ-0033) | "No hold violations found" |
| SS (slow) | +0.87 … +0.88 (9-corner: SS_n40C_1v60 +0.876) | +0.86 / +0.90 |
| TT | +0.43 | +0.44 / +0.45 |
| FF (fast) | +0.27 … +0.29 | +0.28 / +0.29 |

**Verdict: BOTH-CLEAN.** OURS `repair_timing -hold` reports zero hold violations post-CTS, and all 9 corners show positive worst hold slack (min +0.27 ns at FF). REF likewise: all hold corners MET (+0.28 to +0.90). Both designs have hold ≥ 0 across the full corner set. Values are tight and comparable (hold slack is largely library-cell-delay-bounded, so the two micro-architectures land in the same band).

**Evidence:** OURS `phase3/stage3/pnr/openroad.log` (RSZ-0033), `phase3/stage3/pnr/sta_9corner_results.txt`, `phase3/reports/sta_mcorner.txt`; REF `phase3/stage3/multicorner_sta/hold_{ss,tt,ff}.rpt`.
