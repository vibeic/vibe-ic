# L9 sign-off SDC: sky130_fd_sc_hd @ 10 ns (100 MHz), I/O delay = 20% of period = 2 ns
set_units -time ns
create_clock -name core_clock -period 10.0 [get_ports clk]
set_input_delay  2.0 -clock core_clock [all_inputs]
set_output_delay 2.0 -clock core_clock [all_outputs]
