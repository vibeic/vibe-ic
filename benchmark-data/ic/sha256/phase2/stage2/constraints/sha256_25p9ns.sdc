# SHA-256/224 SDC constraints — GENERATED from L9 design constraints.
# Main clock 25.9 ns (~38.6 MHz) per L1/L7/L9; I/O delay 20% of period (L9.1.3).
set_units -time ns
create_clock [get_ports clk] -name core_clock -period 25.9

set non_clock_inputs [all_inputs]
set_input_delay  5.18 -clock core_clock $non_clock_inputs
set_output_delay 5.18 -clock core_clock [all_outputs]
