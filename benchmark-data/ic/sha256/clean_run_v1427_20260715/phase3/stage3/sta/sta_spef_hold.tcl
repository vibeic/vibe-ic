read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

read_verilog /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1427_20260715/phase3/stage3/pnr/sha256_pnr.v
link_design sha256
read_sdc /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1427_20260715/phase3/stage3/pnr/constraint.sdc
read_spef /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1427_20260715/phase3/stage3/extracted/spef_corners/sha256.min.spef
set _f [open /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1427_20260715/phase3/stage3/sta/sta_spef_multicorner.rpt a]
puts $_f "=== HOLD (min-RC corner, SPEF=min) ==="
close $_f
report_worst_slack -min >> /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1427_20260715/phase3/stage3/sta/sta_spef_multicorner.rpt
report_tns >> /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1427_20260715/phase3/stage3/sta/sta_spef_multicorner.rpt
report_checks -min -group_count 3 >> /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1427_20260715/phase3/stage3/sta/sta_spef_multicorner.rpt
exit
