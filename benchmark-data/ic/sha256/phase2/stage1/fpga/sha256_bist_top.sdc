# sha256_bist_top.sdc -- 50 MHz board clock for the DE10-Lite BIST harness.
create_clock -name clk50 -period 20.000 [get_ports {CLOCK_50}]
derive_clock_uncertainty

# Async push-button inputs
set_false_path -from [get_ports {KEY[0]}] -to [all_clocks]
set_false_path -from [get_ports {KEY[1]}] -to [all_clocks]
# LED outputs are observation-only
set_false_path -from [all_clocks] -to [get_ports {LEDR[*]}]
