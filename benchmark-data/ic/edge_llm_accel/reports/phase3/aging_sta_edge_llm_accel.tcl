
read_liberty /foss/pdks/nangate45/libs.ref/NangateOpenCellLibrary/lib/NangateOpenCellLibrary_typical.lib
read_liberty /home/reyerchu/vibe-ic/benchmark-data/ic/edge_llm_accel/input/pdk_local/fakeram45/fakeram45_2048x39.lib
read_verilog /home/reyerchu/vibe-ic/benchmark-data/ic/edge_llm_accel/phase2/stage2/synth/edge_llm_accel_synth.v
link_design edge_llm_accel
read_sdc /home/reyerchu/vibe-ic/benchmark-data/ic/edge_llm_accel/phase3/stage3/pnr/constraint.sdc
# AGING derate (generic, disclosed): late-path (data) paths slowed to model
# NBTI/PBTI/HCI Vt-drift over lifetime, BEYOND the fresh-silicon OCV.
set_timing_derate -late 1.1000
puts "AGING_DERATE_APPLIED late=1.1000 (generic lifetime margin, no foundry aging Liberty)"
if {[catch {report_worst_slack} _e1]} { puts "WNS_ERR: $_e1" }
if {[catch {report_checks -path_delay max -fields {slack}} _e2]} { puts "CHECKS_ERR: $_e2" }
exit
