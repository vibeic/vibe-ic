
read_lef /foss/pdks/nangate45/libs.ref/NangateOpenCellLibrary/techlef/NangateOpenCellLibrary.tech.lef
read_lef /foss/pdks/nangate45/libs.ref/NangateOpenCellLibrary/lef/NangateOpenCellLibrary.lef
read_lef /home/reyerchu/vibe-ic/benchmark-data/ic/edge_llm_accel/input/pdk_local/fakeram45/fakeram45_2048x39.lef
read_liberty /foss/pdks/nangate45/libs.ref/NangateOpenCellLibrary/lib/NangateOpenCellLibrary_typical.lib
read_def /home/reyerchu/vibe-ic/benchmark-data/ic/edge_llm_accel/phase3/stage3/pnr/edge_llm_accel.def
puts "=== ERC: floating nets ==="
# v0.3.16 — ORGANIC #514: -verbose lists the floating net/pin NAMES so the
# by-owner classifier (erc_float_owner_classify.py) can tell benign
# design-for-ECO spare-cell I/O from a real functional float.
if {[catch {report_floating_nets -verbose} _fn]} { puts "ERC_FN_NONFATAL: $_fn" }
puts "=== ERC metrics ==="
if {[catch {report_erc_metrics} _erc]} { puts "ERC_METRICS_NONFATAL: $_erc" }
exit
