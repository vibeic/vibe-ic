# 50 MHz board clock (DE10-Lite CLOCK_50). spm itself targets 100 MHz on SKY130;
# on the MAX10 fabric the BIST harness runs at the board's 50 MHz.
create_clock -name clk_main -period 20.000 [get_ports {CLOCK_50}]
derive_clock_uncertainty
set_false_path -from [get_ports {KEY[*]}]
set_false_path -to   [get_ports {LEDR[*]}]
