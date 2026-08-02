# VIBEIC_SDC_PDK_PROVENANCE: sky130A
# Auto-generated minimal SDC for silicon top (no constraints/*.sdc supplied; clk_period_ns=25.0 clk_port=wb_clk_i)
create_clock -name clk -period 25.0 [get_ports wb_clk_i]
set_input_delay  2 -clock clk [all_inputs]
set_output_delay 2 -clock clk [all_outputs]
# GAP-E2E-7 — no timing exceptions staged in input/constraints or input/reference_flow; none auto-derived
# (auto false_path/multicycle would MASK real violations). Honest single-cycle SDC.

# TAPEOUT-SIGNOFF (DRV) — design-rule constraints so the placer/resizer
# fixes slews (the single-corner-closure confounder: without these a large
# design can PASS typical-corner STA yet carry an ss-corner setup blow-up
# because unconstrained slews explode). Derived from THIS PDK's liberty.
# DRV limits derived from the PDK liberty: max_transition=1.5 ns (from sky130_fd_sc_hd__tt_025C_1v80.lib:default_max_transition); max_capacitance=5.0 pF (from sky130_fd_sc_hd__tt_025C_1v80.lib:max characterised output-pin max_capacitance (PDK-derived ceiling; no library default_max_capacitance declared))
set_max_transition 1.5 [current_design]
set_max_capacitance 5.0 [current_design]
# max_fanout=16 — the design's own staged flow config declares the cap (input/design_src/openlane/user_proj_example/config.json:MAX_FANOUT_CONSTRAINT); set_max_fanout makes repair_design split high-fanout nets so the ss-corner setup slew does not explode (a fanout cap is a hard structural count, immune to the placement-stage parasitic under-estimate). Without it the sign-off max-fanout table is empty BY CONSTRUCTION and the violation count is UNMEASURED.
set_max_fanout 16 [current_design]
