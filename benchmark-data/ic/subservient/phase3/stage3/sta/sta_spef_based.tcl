read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

read_verilog /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/pnr/chip_top_pnr.v
link_design chip_top
read_sdc /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/pnr/constraint.sdc
read_spef /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/extracted/chip_top.spef
report_checks > /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/sta/sta_spef_based.rpt
report_tns >> /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/sta/sta_spef_based.rpt
report_wns >> /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/sta/sta_spef_based.rpt
report_worst_slack -max >> /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/sta/sta_spef_based.rpt
exit
