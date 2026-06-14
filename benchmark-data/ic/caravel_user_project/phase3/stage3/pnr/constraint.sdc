# Auto-generated minimal SDC for silicon top (no constraints/*.sdc supplied; clk_period_ns=25.0 clk_port=wb_clk_i)
create_clock -name clk -period 25.0 [get_ports wb_clk_i]
set_input_delay  2 -clock clk [all_inputs]
set_output_delay 2 -clock clk [all_outputs]
