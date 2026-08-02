
read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ss_100C_1v60.lib

read_verilog /home/reyerchu/_c_car15_run/phase3/stage3/pnr/user_project_wrapper_pnr.v
link_design user_project_wrapper
read_sdc /home/reyerchu/_c_car15_run/phase3/stage3/pnr/constraint.sdc
if {[catch {read_spef /home/reyerchu/_c_car15_run/phase3/stage3/extracted/spef_corners/user_project_wrapper.max.spef} _sp]} { puts "SPEF_ERR: $_sp" }
puts "STA_BASIS: POST_ROUTE_SPEF"
puts "STA_BASIS_NETLIST: user_project_wrapper_pnr.v"
puts "STA_BASIS_SPEF: user_project_wrapper.max.spef (max-RC / late-path corner)"
puts "STA_BASIS_LIBERTY: sky130_fd_sc_hd__ss_100C_1v60.lib (SS)"
# AGING derate (generic, disclosed): late-path (data) paths slowed to model
# NBTI/PBTI/HCI Vt-drift over lifetime, BEYOND the fresh-silicon OCV.
set_timing_derate -late 1.1000
puts "AGING_DERATE_APPLIED late=1.1000 (generic lifetime margin, no foundry aging Liberty)"
if {[catch {report_worst_slack} _e1]} { puts "WNS_ERR: $_e1" }
if {[catch {report_checks -path_delay max -fields {slack}} _e2]} { puts "CHECKS_ERR: $_e2" }
exit
