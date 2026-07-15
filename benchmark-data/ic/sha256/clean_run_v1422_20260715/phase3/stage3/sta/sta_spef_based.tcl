read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

read_verilog /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/pnr/sha256_pnr.v
link_design sha256
read_sdc /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/pnr/constraint.sdc
read_spef /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/extracted/sha256.spef
set_timing_derate -early 0.95
set_timing_derate -late 1.05
report_checks > /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_spef_based.rpt
report_tns >> /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_spef_based.rpt
report_wns >> /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_spef_based.rpt
report_worst_slack -max >> /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_spef_based.rpt
set _ocvf [open /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_spef_based.rpt a]
puts $_ocvf "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV"
close $_ocvf
if {[catch {report_check_types -recovery -removal -max_slew -min_pulse_width -max_capacitance >> /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_spef_based.rpt} _cterr]} {
  set _cf [open /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_spef_based.rpt a]
  puts $_cf "SIGNOFF_CHECK_TYPES_FAILED reason=$_cterr"
  close $_cf
} else {
  set _cf [open /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_spef_based.rpt a]
  puts $_cf "SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width max_capacitance"
  close $_cf
}
exit
