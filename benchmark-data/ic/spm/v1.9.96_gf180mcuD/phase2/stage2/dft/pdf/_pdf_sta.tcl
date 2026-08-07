read_liberty /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib
read_verilog /work/phase3/stage3/pnr/chip_top_pnr.v
link_design chip_top
read_sdc /work/phase3/stage3/pnr/constraint.sdc
read_spef /work/phase3/stage3/extracted/chip_top.spef
report_checks -path_delay max -group_path_count 32 -endpoint_path_count 1 -from [all_registers -clock_pins] -format full_clock_expanded -fields {input_pins} -digits 4 > /work/phase2/stage2/dft/pdf/sta_paths.rpt
exit
