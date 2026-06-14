
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef

read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_def /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/pnr/chip_top.def
# --- Step 22.1: per-layer wire-RC (harmless; required by the estimate fallback) ---
if {[catch {set_wire_rc -signal -layer met1} _swr_sig]} {
  catch {set_wire_rc -layer met1}
}
catch {set_wire_rc -clock -layer met5}
# --- Step 22.2: discover the OpenRCX captable for THIS PDK (chip/PDK-AGNOSTIC) ---
# Derive the PDK root from the tech-LEF path (.../<PDK>/libs.ref/...), then glob the
# OpenLane OpenRCX extraction-model file (rules.openrcx.<pdk>.nom.magic | .nom).
set _tlef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
set _i [string first "/libs.ref/" $_tlef]
set _rules ""
if {$_i > 0} {
  set _root [string range $_tlef 0 [expr {$_i - 1}]]
  set _c [lsort [glob -nocomplain $_root/libs.tech/openlane/rules.openrcx.*.nom.magic]]
  if {[llength $_c] == 0} {
    set _c [lsort [glob -nocomplain $_root/libs.tech/openlane/rules.openrcx.*.nom]]
  }
  if {[llength $_c] > 0} { set _rules [lindex $_c 0] }
}
if {$_rules ne ""} {
  # --- Step 22.3a: full OpenRCX extraction with the captable (sign-off SPEF) ---
  puts "SPEF_OPENRCX_CAPTABLE: $_rules"
  catch {define_process_corner -ext_model_index 0 X}
  if {[catch {extract_parasitics -ext_model_file $_rules -corner_cnt 1 -max_res 50 -coupling_threshold 0.1} _ee]} {
    puts "SPEF_EXTRACT_PARASITICS_NONFATAL: $_ee"
  }
} else {
  # --- Step 22.3b: fallback — no captable for this PDK; estimate_parasitics ---
  puts "SPEF_NO_CAPTABLE_FALLBACK_ESTIMATE"
  catch {global_route}
  if {[catch {estimate_parasitics -global_routing} _pe1]} {
    catch {estimate_parasitics -placement}
  }
}
# --- Step 22.4: write the SPEF ---
if {[catch {write_spef /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/extracted/chip_top.spef} spef_err]} {
  puts "SPEF_WRITE_FAIL: $spef_err"
}
exit
