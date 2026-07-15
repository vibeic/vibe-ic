
read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

read_verilog /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1427_20260715/phase2/stage2/synth/sha256_synth.v
link_design sha256
read_sdc /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1427_20260715/phase3/stage3/pnr/constraint.sdc
# AGING derate (generic, disclosed): late-path (data) paths slowed to model
# NBTI/PBTI/HCI Vt-drift over lifetime, BEYOND the fresh-silicon OCV.
set_timing_derate -late 1.1000
puts "AGING_DERATE_APPLIED late=1.1000 (generic lifetime margin, no foundry aging Liberty)"
if {[catch {report_worst_slack} _e1]} { puts "WNS_ERR: $_e1" }
if {[catch {report_checks -path_delay max -fields {slack}} _e2]} { puts "CHECKS_ERR: $_e2" }
exit
