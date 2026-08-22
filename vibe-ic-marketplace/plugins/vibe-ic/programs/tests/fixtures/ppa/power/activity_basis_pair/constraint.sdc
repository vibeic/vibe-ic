# Same constraints for BOTH power runs. The ONLY difference between the two
# runs is the activity basis; everything here is shared.
create_clock -name clk -period 24.0 [get_ports clk]
set_input_delay  2.0 -clock clk [all_inputs -no_clocks]
set_output_delay 2.0 -clock clk [all_outputs]
