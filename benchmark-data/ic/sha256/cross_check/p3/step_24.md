# Step 24 — IR drop (PDNSim on OURS) (GAP CLOSED)

**Gap:** OURS `pnr.tcl` never generated a PDN — `routed.def` has **0 SPECIALNETS** and no VPWR/VGND nets. PDNSim could not run (PSM-0028 "Cannot find net VPWR"). REF had a full PDN (9,290 VPWR + 9,290 VGND).

**What ran (real tool):** Rebuilt the power grid on OURS `post_hold.def` with OpenROAD — `add_global_connection` (VPWR/VPB, VGND/VNB), `set_voltage_domain`, `define_pdn_grid`, met1 followpin rails + met4/met5 straps (pitch 56 um), `pdngen` — then `analyze_power_grid` (PDNSim). Script: `phase3/stage3/ir_drop/xc_pdn_ir_em.tcl`.

| Metric | OURS VPWR | OURS VGND | REF VPWR | REF VGND |
|---|---|---|---|---|
| Worst IR drop | 4.37e-04 V | 4.18e-04 V | 3.84e-04 V | 4.29e-04 V |
| Average IR drop | 1.26e-04 V | 1.23e-04 V | 1.20e-04 V | 1.40e-04 V |
| Percentage of Vdd | **0.02 %** | 0.02 % | 0.02 % | 0.02 % |
| Total power (grid) | 1.11e-02 W | — | 5.61e-03 W | — |
| Supply voltage | 1.80 V | 0 V | 1.80 V | — |
| Limit | 5.0 % Vdd | | 5.0 % Vdd | |

**Verdict: GAP CLOSED / BOTH-CLEAN / IN-RANGE.** With a freshly-built PDN, OURS IR drop is **0.02 % of Vdd** — identical to REF (0.02 %) and ~250x under the 5 % sign-off limit. PDNSim reports "All shapes on net VPWR/VGND are connected." OURS grid total power (11.1 mW) is ~2x REF (5.6 mW), consistent with OURS having ~27 % more cells and a denser carry-save switching profile.

**Evidence:** `phase3/stage3/ir_drop/pdn_ir_em.log` (IR report VPWR/VGND, "Percentage drop 0.02 %"), `phase3/stage3/pnr/pdn.def`; REF `reports/phase3/ir_drop.json`.
