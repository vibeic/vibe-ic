# Step 17 — Placement density + legality

**What ran:** Read OURS OpenROAD global+detailed placement log (GPL/DPL "Placement Analysis"); compared with REF.

| Metric | OURS | REF |
|---|---|---|
| Global placement convergence | finished iter 457 | converged |
| Target density | 0.20 | 0.20 |
| Final placement area | 101,631 um² (+0.00%) | 93,120 um² (+0.00%) |
| Legalized HPWL | 374,083 um (pre-CTS) → 393,936 um (post-hold) | comparable |
| Detailed-placement displacement | avg 1.6 um / max 7.4 um (then avg 0.1 um after final legalize) | clean |
| Legality | legalized (detailed_placement clean, no overlaps reported) | legalized |

**Verdict: BOTH-CLEAN / IN-RANGE.** OURS global placement converged at density 0.20 and detailed_placement legalized with no overlap errors; the post-hold re-legalize shows avg displacement 0.1 um (tight). HPWL ~374k–394k um is consistent with a 12.1k-cell carry-save design. REF legalizes comparably at 93k um². Difference in placement area tracks the cell-count delta (12,148 vs 9,546).

**Evidence:** OURS `phase3/stage3/pnr/openroad.log` (GPL-1001/1014, "Placement Analysis", legalized HPWL).
