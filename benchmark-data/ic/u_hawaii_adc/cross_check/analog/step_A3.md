# Step A3 — netlist gen  ·  Verdict: BOTH-CLEAN
OURS: ldo.sp + delta_sigma.sp (SG13G2 LEVEL=1 standin), each with .subckt, netlisted + simulated.
REF: golden has only a flat chip-level extracted netlist (sg13_lv_nmos/pmos, 2379 device lines) — no per-block deck. Device CLASS matches (sg13 lv MOS).
