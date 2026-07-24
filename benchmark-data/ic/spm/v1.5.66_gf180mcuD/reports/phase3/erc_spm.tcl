
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lef/gf180mcu_fd_sc_mcu7t5v0.lef

read_liberty /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib
read_def /home/reyerchu/campaign_v1566/spm/converge_1.5.66_gf180mcuD/phase3/stage3/pnr/spm.def
puts "=== ERC: floating nets ==="
# v0.3.16 — ORGANIC #514: -verbose lists the floating net/pin NAMES so the
# by-owner classifier (erc_float_owner_classify.py) can tell benign
# design-for-ECO spare-cell I/O from a real functional float.
if {[catch {report_floating_nets -verbose} _fn]} { puts "ERC_FN_NONFATAL: $_fn" }
puts "=== ERC metrics ==="
if {[catch {report_erc_metrics} _erc]} { puts "ERC_METRICS_NONFATAL: $_erc" }
exit
