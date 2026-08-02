read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_verilog /work/phase3/stage3/pnr/user_project_wrapper_pnr.v
link_design user_project_wrapper
read_sdc /work/phase3/stage3/pnr/constraint.sdc
read_spef /work/phase3/stage3/extracted/user_project_wrapper.spef
report_checks -path_delay max -group_path_count 32 -endpoint_path_count 1 -from [all_registers -clock_pins] -format full_clock_expanded -fields {input_pins} -digits 4 > /work/phase2/stage2/dft/pdf/sta_paths.rpt
exit
