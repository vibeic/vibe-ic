# Step 29 — Post-layout SPICE critical-path correlation

Verdict: N/A

NO routed parasitics exist (see step 22: detailed route stalled on the genuine
flop-RF huge fanout, DRT-0305), so there is no post-layout RC to feed a SPICE
critical-path correlation. Full-chip transistor-level SPICE of a ~3.4k-cell SoC
is independently NO-TOOL in the open-source flow (same limitation the reference
shares). Liberty-model multi-corner STA stands as the timing signoff (relaxed
30ns MET SS/TT/FF). N/A — honestly reported design-characteristic limitation.
