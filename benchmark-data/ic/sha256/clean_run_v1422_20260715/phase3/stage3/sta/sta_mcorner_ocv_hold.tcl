read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ff_n40C_1v95_ccsnoise.lib

read_verilog /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/eco/sha256_eco.v
link_design sha256
read_sdc /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/pnr/constraint.sdc
read_spef /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/extracted/spef_corners/sha256.min.spef
set_timing_derate -early 0.95
set_timing_derate -late 1.05
set _f [open /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_mcorner_ocv_posteco.rpt a]
puts $_f "=== HOLD corner: process=FF liberty, SPEF=sha256.min.spef ==="
puts $_f "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV"
close $_f
report_worst_slack -min >> /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_mcorner_ocv_posteco.rpt
report_tns >> /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_mcorner_ocv_posteco.rpt
catch {report_checks -min -group_path_count 3 -fields {slew capacitance} >> /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_mcorner_ocv_posteco.rpt}
if {[catch {report_check_types -recovery -removal -max_slew -min_pulse_width -max_capacitance >> /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_mcorner_ocv_posteco.rpt} _cterr]} {
  set _cf [open /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_mcorner_ocv_posteco.rpt a]
  puts $_cf "SIGNOFF_CHECK_TYPES_FAILED reason=$_cterr"
  close $_cf
} else {
  set _cf [open /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_mcorner_ocv_posteco.rpt a]
  puts $_cf "SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width max_capacitance"
  close $_cf
}
exit
