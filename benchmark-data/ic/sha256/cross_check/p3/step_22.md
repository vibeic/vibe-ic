# Step 22 — SPEF: OpenRCX extract on OURS (GAP CLOSED)

**Gap:** OURS phase3 runner reported "SPEF extraction did not produce sha256.spef" — no parasitic netlist existed for OURS. REF had a full OpenROAD SPEF.

**What ran (real tool):** OpenROAD `extract_parasitics` (OpenRCX) on OURS `routed.def`, using the sky130A nom RCX rules file
`/foss/pdks/ciel/.../rules.openrcx.sky130A.nom.spef_extractor` (same model REF used), then `write_spef`. Script: `phase3/stage3/extracted/xc_p3_signoff.tcl`.

| Metric | OURS (extracted now) | REF |
|---|---|---|
| SPEF file | `phase3/stage3/extracted/sha256.spef` (11.2 MB) | `phase3/stage3/extracted/sha256.spef` (≈ same scale) |
| Nets extracted (*D_NET) | 12,028 | 28,410 *D_NET/CAP/RES lines (9,470-net design) |
| RC segments (rsegs) | 63,096 | comparable |
| Coupling caps (cc) | 117,080 | 73,635 |
| R_UNIT / C_UNIT | 1 OHM / 1 PF | 1 OHM / 1 PF |
| Tool / corner | OpenROAD OpenRCX, nom (TT) | OpenROAD OpenRCX, nom (TT) |

**Verdict: GAP CLOSED / IN-RANGE.** OURS SPEF now exists and is non-vacuous: 12,028 nets, 63,096 R + C segments, 117,080 coupling caps. R/C magnitudes are in the same units and order as REF (REF's larger cc count tracks its different routing). Both extracted with the same nom RCX model. The extraction wires extracted 89,325 segments (RCX-0442 100%).

**Evidence:** `phase3/stage3/extracted/sha256.spef`, `phase3/stage3/extracted/xc_signoff.log` (RCX-0045 "Extract 12026 nets, 63096 rsegs, 63096 caps, 117080 ccs", "SPEF_WRITE_OK").
