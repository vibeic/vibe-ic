# The activity basis is DECLARED the way the runner's own power session declares
# it. Not a label of convenience: this script reads no VCD and no SAIF (grep
# it), so OpenSTA's activity model here is vectorless by construction.
puts "POWER_ANALYSIS_MODE: vectorless_sdc"
read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_verilog /home/reyerchu/_jxlayer/run/trials/c05/phase3/stage3/pnr/spm_pnr.v
link_design spm
read_spef /home/reyerchu/_jxlayer/run/trials/c05/phase3/stage3/extracted/spm.spef
read_sdc /home/reyerchu/_jxlayer/run/trials/c05/phase3/stage3/pnr/constraint.sdc
report_power
