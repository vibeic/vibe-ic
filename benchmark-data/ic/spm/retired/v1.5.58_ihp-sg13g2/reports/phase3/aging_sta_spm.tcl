
read_liberty /foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib

read_verilog /home/reyerchu/campaign_v1558/spm/converge_1.5.58_ihp-sg13g2/phase2/stage2/synth/spm_synth.v
link_design spm
read_sdc /home/reyerchu/campaign_v1558/spm/converge_1.5.58_ihp-sg13g2/phase3/stage3/pnr/constraint.sdc
# AGING derate (generic, disclosed): late-path (data) paths slowed to model
# NBTI/PBTI/HCI Vt-drift over lifetime, BEYOND the fresh-silicon OCV.
set_timing_derate -late 1.1000
puts "AGING_DERATE_APPLIED late=1.1000 (generic lifetime margin, no foundry aging Liberty)"
if {[catch {report_worst_slack} _e1]} { puts "WNS_ERR: $_e1" }
if {[catch {report_checks -path_delay max -fields {slack}} _e2]} { puts "CHECKS_ERR: $_e2" }
exit
