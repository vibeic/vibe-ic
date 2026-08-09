# VIBEIC_SDC_PDK_PROVENANCE: ihp-sg13g2
# Auto-generated minimal SDC for silicon top (no constraints/*.sdc supplied; clk_period_ns=10.0 clk_port=clk)
create_clock -name clk -period 10.0 [get_ports clk]
set_input_delay  2 -clock clk [all_inputs]
set_output_delay 2 -clock clk [all_outputs]
# GAP-E2E-7 — no timing exceptions staged in input/constraints or input/reference_flow; none auto-derived
# (auto false_path/multicycle would MASK real violations). Honest single-cycle SDC.

# TAPEOUT-SIGNOFF (DRV) — design-rule constraints so the placer/resizer
# fixes slews (the single-corner-closure confounder: without these a large
# design can PASS typical-corner STA yet carry an ss-corner setup blow-up
# because unconstrained slews explode). Derived from THIS PDK's liberty.
# DRV limits derived from the PDK liberty: max_transition=2.5074 ns (from sg13g2_stdcell_typ_1p20V_25C.lib:default_max_transition); max_capacitance=0.3 pF (from sg13g2_stdcell_typ_1p20V_25C.lib:default_max_capacitance)
set_max_transition 2.5074 [current_design]
set_max_capacitance 0.3 [current_design]
