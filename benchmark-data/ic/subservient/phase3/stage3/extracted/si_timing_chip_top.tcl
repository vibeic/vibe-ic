# === Vibe-IC timing-window-aware SI screen — OpenSTA timing JSON emitter ===
# Produces the per-pin arrival-window + slew JSON consumed by
# si_signoff_timing_aware.score_si_timing_aware(). Chip-AGNOSTIC.
read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_verilog /foss/designs/_bench6_v100_r1/subservient/phase2/stage2/synth/chip_top_synth.v
link_design chip_top
read_sdc /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/pnr/constraint.sdc
read_spef /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/extracted/chip_top.spef

proc _si_capture {cmd args} {
  sta::redirect_string_begin
  catch {eval $cmd $args}
  return [sta::redirect_string_end]
}
proc _si_jnum {x} { if {$x eq ""} { return "null" } else { return $x } }

set _si_out [open /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/extracted/chip_top_si_timing.json w]
puts $_si_out "{"
puts $_si_out "  \"tool\": \"OpenSTA\","
puts $_si_out "  \"design\": \"chip_top\","
puts $_si_out "  \"time_unit\": \"ns\","
puts $_si_out "  \"vdd_v\": 1.8,"
puts $_si_out "  \"pins\": {"
set _si_first 1
set _si_n 0
# Emit one pin/port record (arrival windows + slews). Walk BOTH internal pins
# AND top-level ports so primary-input nets (driven by an input pad, arrival =
# input delay) also get a switching window — without ports they'd fall back to
# the conservative "unknown window => assume overlap" path.
proc _si_emit {obj out first_var n_var} {
  upvar $first_var _si_first
  upvar $n_var _si_n
  set _si_pn [get_full_name $obj]
  set _si_arr [_si_capture report_arrival $obj]
  set _si_armn ""; set _si_armx ""; set _si_afmn ""; set _si_afmx ""
  regexp {r ([-0-9.eE+]+):([-0-9.eE+]+)} $_si_arr -> _si_armn _si_armx
  regexp {f ([-0-9.eE+]+):([-0-9.eE+]+)} $_si_arr -> _si_afmn _si_afmx
  if {$_si_armn eq "" && $_si_afmn eq ""} { return }
  set _si_slw [_si_capture report_slews $obj]
  set _si_srmn ""; set _si_srmx ""; set _si_sfmn ""; set _si_sfmx ""
  regexp {\^ ([-0-9.eE+]+):([-0-9.eE+]+)} $_si_slw -> _si_srmn _si_srmx
  regexp {v ([-0-9.eE+]+):([-0-9.eE+]+)} $_si_slw -> _si_sfmn _si_sfmx
  if {!$_si_first} { puts $out "," }
  set _si_first 0
  incr _si_n
  puts -nonewline $out "    \"$_si_pn\": {\"arr_rise_min\": [_si_jnum $_si_armn], \"arr_rise_max\": [_si_jnum $_si_armx], \"arr_fall_min\": [_si_jnum $_si_afmn], \"arr_fall_max\": [_si_jnum $_si_afmx], \"slew_rise_max\": [_si_jnum $_si_srmx], \"slew_fall_max\": [_si_jnum $_si_sfmx]}"
}
foreach _si_p [get_pins -hierarchical *] { _si_emit $_si_p $_si_out _si_first _si_n }
if {![catch {set _si_ports [get_ports *]}]} {
  foreach _si_pp $_si_ports { _si_emit $_si_pp $_si_out _si_first _si_n }
}
puts $_si_out ""
puts $_si_out "  }"
puts $_si_out "}"
close $_si_out
puts "SI_TIMING_JSON_EMIT_DONE pins=$_si_n out=/foss/designs/_bench6_v100_r1/subservient/phase3/stage3/extracted/chip_top_si_timing.json"
