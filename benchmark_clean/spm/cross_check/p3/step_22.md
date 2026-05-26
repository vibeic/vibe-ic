# Step 21 — SPEF / RC Extraction (GAP-CLOSE)

## What ran
OURS originally had a GAP: `extract_spm.tcl` used `estimate_parasitics -global_routing`
on the canonical `spm.def` in a fresh OpenROAD session — global_route had not been run
in that session, so it errored (`EST-0005`), the `-placement` fallback wrote zero RC, and
`write_spef` failed (`RCX-0134 no extraction data`). No `spm.spef` was produced
(see waivers.json VIBE-IC-PLUGIN-PHASE3-SPEF-EXTRACT).

GAP closed by mirroring the REF's real OpenRCX flow on OUR **routed** DEF:
- Tool: OpenROAD 26Q1 `extract_parasitics` (OpenRCX) in iic-eda container.
- TCL: `phase3/stage3/extracted/extract_openrcx_xc.tcl`
- Inputs: sky130_fd_sc_hd nom techlef + lef + tt lib, `routed.def`,
  rules `rules.openrcx.sky130A.nom.spef_extractor`.
- Output: `phase3/stage3/extracted/spm_xc.spef` (182 KB), log `spef_xc.log`.

## OUR metric
- Tool result: `Extract 279 nets, 1294 rsegs, 1294 caps, 1893 ccs` / `281 nets finished`.
- Total R = 16,092.85 Ω over 1013 RC segments.
- Total C = 0.4714 pF over 5080 cap entries.

## REF metric
- `phase3/stage3/extracted/spm.spef` (244 KB), produced by the same OpenRCX flow
  (`full_repnr.log` lines 553-562: `Final 1357 rc segments`, `Extract 330 nets, 1687 rsegs, 1687 caps, 1761 ccs`).
- Total R = 21,151.70 Ω, Total C = 0.6044 pF.

## Side-by-side
| metric | OURS | REF | ratio O/R |
|---|---|---|---|
| nets in SPEF | 279/281 | 330 | 0.85 |
| total R (Ω) | 16,093 | 21,152 | 0.76 |
| total C (pF) | 0.471 | 0.604 | 0.78 |
| rc segments | 1013 | 1357 | 0.75 |

## Verdict: IN-RANGE (GAP closed)
OUR carry-save netlist is leaner (281 vs 330 nets); R and C scale down
proportionally (~0.76-0.78), consistent with the smaller net count. Both SPEFs
are real OpenRCX extractions on identical 200x200 µm die / sky130A nom corner.
No anomalous parasitic magnitude. Both are physically sensible.
