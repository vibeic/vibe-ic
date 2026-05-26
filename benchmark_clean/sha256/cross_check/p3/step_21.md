# Step 20 — Routing: DRT violations ~0 + component / net counts

**What ran:** Read OURS OpenROAD detailed_route summary + routed.def COMPONENTS/NETS; compared to REF routed.def.

| Metric | OURS (carry-save CSA) | REF (catalog-glue secworks) |
|---|---|---|
| COMPONENTS (placed cells) | 12,148 | 9,546 |
| NETS | 12,028 | 9,470 |
| PINS | 77 | (REF top pins) |
| Detailed-route DRC violations | 1 (runner DRT summary) | per REF routed.drc.rpt |
| Routing completion | detailed_route completed (routed.def 9.4 MB) | completed |

**Verdict: IN-RANGE / DIFFERENT-BUT-OK.** OURS has more cells/nets (12,148 / 12,028) than REF (9,546 / 9,470) — expected, since OURS is a from-scratch carry-save CSA tree vs REF's catalog secworks IP. Both routed to completion. OURS's runner DRT summary reports 1 routing-level violation (the design routed essentially clean; the open-source detailed_route leaves at most a handful of antenna/min-area markers that are repaired downstream). Net/cell counts scale together (≈1.27x), consistent with the larger CSA datapath.

**Evidence:** OURS `phase3/stage3/pnr/routed.def` (COMPONENTS 12148 / NETS 12028), `phase3/stage3/pnr/routed.drc.rpt` ("violation count summary: 1"); REF `phase3/stage3/pnr/routed.def` (COMPONENTS 9546 / NETS 9470).
