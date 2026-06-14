
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef

read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_def /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/pnr/chip_top.def
puts "=== DESIGN AREA (pre-fill) ==="
report_design_area
# ECO-aware fill: filler_placement only ADDS filler instances into row
# gaps; it never removes or overlaps existing (dont_touch) instances, so
# the Step 18 spares are preserved by construction.
if {[catch {filler_placement {sky130_fd_sc_hd__decap_12 sky130_fd_sc_hd__decap_8 sky130_fd_sc_hd__decap_6 sky130_fd_sc_hd__decap_4 sky130_fd_sc_hd__decap_3 sky130_fd_sc_hd__fill_8 sky130_fd_sc_hd__fill_4 sky130_fd_sc_hd__fill_2 sky130_fd_sc_hd__fill_1}} _fp_err]} {
  puts "FILLER_PLACEMENT_NONFATAL: $_fp_err"
}
puts "=== DESIGN AREA (post-fill) ==="
report_design_area
# v0.3.9 — ORGANIC #510: TRUE row-area utilization (occupied CORE-class
# master area / placement-row area), measured from odb. report_design_area
# above is CORE-area utilization (logic area / core area) — a different
# axis: a design whose rows are fully tiled with fillers/decap/tap can sit
# at low core-util yet ~100% row-util. The fill gate's rows-already-full
# path needs ROW-util; emit it explicitly so the writer never mislabels
# core-util as row-util. chip-AGNOSTIC: pure odb geometry, no chip names.
# v0.3.26 — ORGANIC #526: OpenROAD 26Q1 renamed the odb Rect accessors
# getDX/getDY -> dx/dy; the old names made the whole catch fire and the
# measurement silently degraded to NA on a fully-filled DEF. Probe the
# current names first and fall back to the legacy ones so BOTH container
# generations measure row-util.
proc _rcw {bb} {
  if {[catch {$bb dx} _w]} { set _w [$bb getDX] }
  return $_w
}
proc _rch {bb} {
  if {[catch {$bb dy} _h]} { set _h [$bb getDY] }
  return $_h
}
if {[catch {
  set _blk [ord::get_db_block]
  set _rowA 0.0
  foreach _r [$_blk getRows] {
    set _bb [$_r getBBox]
    set _rowA [expr {$_rowA + double([_rcw $_bb]) * double([_rch $_bb])}]
  }
  set _occ 0.0
  foreach _i [$_blk getInsts] {
    set _m [$_i getMaster]
    if {[string match "CORE*" [$_m getType]]} {
      set _occ [expr {$_occ + double([$_m getWidth]) * double([$_m getHeight])}]
    }
  }
  if {$_rowA > 0} {
    puts "ROW_UTILIZATION_PCT [expr {100.0 * $_occ / $_rowA}]"
  } else {
    puts "ROW_UTILIZATION_PCT NA"
  }
} _rowerr]} {
  puts "ROW_UTILIZATION_PCT NA ($_rowerr)"
}
write_def /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/pnr/filled.def
exit
