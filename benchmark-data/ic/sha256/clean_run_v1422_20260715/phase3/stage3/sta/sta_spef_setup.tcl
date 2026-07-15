set _f [open /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_spef_multicorner.rpt w]
puts $_f "# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)"
puts $_f "# SETUP corner: max-RC   HOLD corner: min-RC"
puts $_f "# corners_available: max,min,nom"
close $_f
read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

read_verilog /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/pnr/sha256_pnr.v
link_design sha256
read_sdc /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/pnr/constraint.sdc
read_spef /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/extracted/spef_corners/sha256.max.spef
set _f [open /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_spef_multicorner.rpt a]
puts $_f "=== SETUP (max-RC corner, SPEF=max) ==="
close $_f
report_worst_slack -max >> /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_spef_multicorner.rpt
report_tns >> /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_spef_multicorner.rpt
report_checks -max -group_count 3 >> /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/sta/sta_spef_multicorner.rpt
exit
