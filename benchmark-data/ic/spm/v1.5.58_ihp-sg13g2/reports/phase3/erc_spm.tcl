
read_lef /foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lef/sg13g2_tech.lef
read_lef /foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef

read_liberty /foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib
read_def /home/reyerchu/campaign_v1558/spm/converge_1.5.58_ihp-sg13g2/phase3/stage3/pnr/spm.def
puts "=== ERC: floating nets ==="
# v0.3.16 — ORGANIC #514: -verbose lists the floating net/pin NAMES so the
# by-owner classifier (erc_float_owner_classify.py) can tell benign
# design-for-ECO spare-cell I/O from a real functional float.
if {[catch {report_floating_nets -verbose} _fn]} { puts "ERC_FN_NONFATAL: $_fn" }
puts "=== ERC metrics ==="
if {[catch {report_erc_metrics} _erc]} { puts "ERC_METRICS_NONFATAL: $_erc" }
exit
