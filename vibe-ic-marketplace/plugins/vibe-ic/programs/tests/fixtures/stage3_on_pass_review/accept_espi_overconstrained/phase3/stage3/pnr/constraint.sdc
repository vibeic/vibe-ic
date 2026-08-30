# Auto-generated minimal SDC for silicon top (no constraints/*.sdc supplied; clk_period_ns=20.0 clk_port=clk)
create_clock -name clk -period 20.0 [get_ports clk]
set_input_delay  2 -clock clk [all_inputs]
set_output_delay 2 -clock clk [all_outputs]
