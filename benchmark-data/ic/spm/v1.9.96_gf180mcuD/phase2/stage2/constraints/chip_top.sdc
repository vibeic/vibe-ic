# VIBEIC_SDC_PDK_PROVENANCE: gf180mcuD
# Auto-generated minimal SDC for silicon top (no constraints/*.sdc supplied; clk_period_ns=24.0 clk_port=clk)
create_clock -name clk -period 24.0 [get_ports clk]
set _vibeic_clk_ports [get_ports clk]
set _vibeic_data_in {}
foreach _vibeic_p [all_inputs] {
  if {[lsearch -exact $_vibeic_clk_ports $_vibeic_p] < 0} { lappend _vibeic_data_in $_vibeic_p }
}
puts "VIBEIC_INPUT_DELAY_PORTS [llength $_vibeic_data_in] of [llength [all_inputs]] (clock port(s) excluded — OpenSTA rejects set_input_delay on the port its own clock is defined on)"
if {[llength $_vibeic_data_in] > 0} { set_input_delay  2 -clock clk $_vibeic_data_in }
set_output_delay 2 -clock clk [all_outputs]
# GAP-E2E-7 — no timing exceptions staged in input/constraints or input/reference_flow; none auto-derived
# (auto false_path/multicycle would MASK real violations). Honest single-cycle SDC.

# TAPEOUT-SIGNOFF (DRV) — design-rule constraints so the placer/resizer
# fixes slews (the single-corner-closure confounder: without these a large
# design can PASS typical-corner STA yet carry an ss-corner setup blow-up
# because unconstrained slews explode). Derived from THIS PDK's liberty.
# DRV limits derived from the PDK liberty: max_capacitance=4.756 pF (from gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib:max characterised output-pin max_capacitance (PDK-derived ceiling; no library default_max_capacitance declared))
set_max_capacitance 4.756 [current_design]
