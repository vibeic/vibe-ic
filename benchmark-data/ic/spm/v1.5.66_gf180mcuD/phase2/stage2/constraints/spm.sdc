# VIBEIC_SDC_PDK_PROVENANCE: gf180mcuD
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
# DRV limits derived from the PDK liberty: max_capacitance=4.756 pF (from gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib:max characterised output-pin max_capacitance (PDK-derived ceiling; no library default_max_capacitance declared))
set_max_capacitance 4.756 [current_design]
