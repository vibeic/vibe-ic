
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef

read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_def /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1427_20260715/phase3/stage3/pnr/sha256.def
puts "=== ERC: floating nets ==="
# v0.3.16 — ORGANIC #514: -verbose lists the floating net/pin NAMES so the
# by-owner classifier (erc_float_owner_classify.py) can tell benign
# design-for-ECO spare-cell I/O from a real functional float.
if {[catch {report_floating_nets -verbose} _fn]} { puts "ERC_FN_NONFATAL: $_fn" }
puts "=== ERC metrics ==="
if {[catch {report_erc_metrics} _erc]} { puts "ERC_METRICS_NONFATAL: $_erc" }
exit
