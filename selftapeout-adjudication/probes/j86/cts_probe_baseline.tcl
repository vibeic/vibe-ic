# J86 CTS PROBE baseline
# -buf_list {gf180mcu_fd_sc_mcu7t5v0__clkbuf_4}  -root_buf {gf180mcu_fd_sc_mcu7t5v0__clkbuf_16}
# stops after CTS + census; no legalizer, no ladder.


set_thread_count 32
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lef/gf180mcu_fd_sc_mcu7t5v0.lef

define_corners ss tt ff
read_liberty -corner ss /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__ss_125C_4v50.lib
read_liberty -corner tt /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib
read_liberty -corner ff /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__ff_n40C_5v50.lib

puts "PROBE_STAGE: read_def"
read_def /home/reyerchu/_jself_priv/proj/matmul_d3800/phase3/stage3/pnr/placed.def

read_sdc /home/reyerchu/_jself_priv/proj/matmul_d3800/phase3/stage3/pnr/constraint.sdc
# === v0.2.14 — restrict the resizer/CTS/repair cell pool (after link_design,
# before any optimization). Prevents OpenROAD from inserting PnR-forbidden cells
# (probe / lpflow / DRC-failed) that TritonRoute then cannot route (DRT-0085).
# See _dont_use_tcl. ===
# === v1.2.86 — GENERAL characterization/lpflow/delay do-not-use fallback ===
# Works even when the PDK ships no drc_exclude.cells (iic-osic-tools):
# excludes probe/probec/lpflow (unroutable → DRT-0085) + clkdly*
# (clock-DELAY masters the resizer must never use as a SIGNAL buffer)
# + dly*/delay* (SIGNAL DELAY macros — dlya/b/c/d, dlygate, dlymetal,
# DLY1D1…DLY4D1: high-intrinsic-delay cells the resizer/buffer_ports
# must never insert as a signal/port buffer, or they dominate the
# SLOW-corner setup path / get chosen as a slew-fix buffer).
# Family STEMS matched case-insensitively via OpenROAD's own
# get_lib_cells, so BOTH the open-PDK <lib>__<fn> spelling AND bare
# commercial names are caught; GUARDED so the buffer pool can never be
# emptied. NAMING-CONVENTION-AGNOSTIC, no design literal.
# -regexp is MANDATORY here, not stylistic: OpenSTA honours -nocase
# ONLY in regexp mode -- in glob mode it warns
# `[WARNING STA-0358] -nocase ignored without -regexp` and matches
# case-SENSITIVELY. Measured in-container on a commercial 180nm
# library: `get_lib_cells -nocase -quiet *dly*` -> 0 cells, while
# `-quiet *DLY*` -> 4 (DLY1D1..DLY4D1). The block then printed
# DONT_USE_FALLBACK_APPLIED: 0 -- announcing that the guard had run
# while it excluded nothing. Patterns are therefore REGEXES, and
# OpenSTA anchors them to the WHOLE cell name, so each needs the
# leading/trailing `.*` (measured: `dly` -> 0, `.*dly.*` -> 4).
proc _du_nbuf {} {
  set _n 0
  foreach _c [get_lib_cells -quiet *] {
    if {[catch {set _b [get_property $_c is_buffer]}]} { continue }
    if {!$_b} { continue }
    if {[catch {set _d [get_property $_c dont_use]}]} { set _d 0 }
    if {!$_d} { incr _n }
  }
  return $_n
}
set _du_before 0
catch {set _du_before [_du_nbuf]}
set _duf 0
set _du_all {}
foreach _du_pat {.*probe_.* .*probec_.* .*lpflow.* .*clkdly.* .*dly.* .*delay.*} {
  set _du_cells [get_lib_cells -regexp -nocase -quiet $_du_pat]
  if {[llength $_du_cells] > 0} {
    if {[catch {set_dont_use $_du_cells} _duf_e]} {
      puts "DONT_USE_FALLBACK_NONFATAL: $_du_pat -- $_duf_e"
    } else {
      incr _duf [llength $_du_cells]
      set _du_all [concat $_du_all $_du_cells]
    }
  }
}
set _du_after $_du_before
catch {set _du_after [_du_nbuf]}
if {$_du_before > 0 && $_du_after == 0} {
  catch {unset_dont_use $_du_all}
  puts "DONT_USE_FALLBACK_REVERTED: the exclusion would have left 0 usable buffer cells (was $_du_before) -- reverted so the resizer/CTS keep a pool; reported, never silently applied"
  set _duf 0
  set _du_after $_du_before
}
puts "DONT_USE_FALLBACK_APPLIED: $_duf characterization/lpflow/delay cell(s) excluded by family-name fallback; usable buffer cells $_du_before -> $_du_after"
set _du_root /foss/pdks/gf180mcuD
set _du_file ""
foreach _du_d {librelane openlane} {
  foreach _du_nm {pnr_excluded.cells drc_exclude.cells} {
    if {$_du_file ne ""} { continue }
    set _du_c [lsort [glob -nocomplain $_du_root/libs.tech/$_du_d/*/$_du_nm]]
    if {[llength $_du_c] > 0} { set _du_file [lindex $_du_c 0] }
  }
}
if {$_du_file eq "" && [file exists /foss/pdks/gf180mcuD/libs.tech/librelane/gf180mcu_fd_sc_mcu7t5v0/pnr_exclude.cells]} { set _du_file /foss/pdks/gf180mcuD/libs.tech/librelane/gf180mcu_fd_sc_mcu7t5v0/pnr_exclude.cells }
if {$_du_file ne "" && [file exists $_du_file]} {
  set _du_f [open $_du_file r]
  set _du_n 0
  while {[gets $_du_f _du_cell] >= 0} {
    set _du_cell [string trim $_du_cell]
    if {$_du_cell eq "" || [string index $_du_cell 0] eq "#"} { continue }
    if {[catch {set_dont_use $_du_cell} _du_e]} {
      puts "SET_DONT_USE_NONFATAL: $_du_cell -- $_du_e"
    } else { incr _du_n }
  }
  close $_du_f
  catch {report_dont_use}
  puts "DONT_USE_APPLIED: $_du_n cells from $_du_file"
} else {
  puts "DONT_USE_SKIPPED: PNR exclude file not found (librelane/openlane × pnr_excluded/drc_exclude all absent)"
}
# === restore the resizer swap pool to THIS library's own buffer
# family, BEFORE the first timing-driven step.
# getSwappableCells drops any equivalent cell more than 4.0X the
# source cell in area OR leakage, and PreChecks::checkSlewLimit
# computes the BEST ACHIEVABLE transition over the WEAKEST buffer's
# surviving pool. On a family wider than 4.0X the strong buffers are
# invisible, so the check reports an infeasible slew target that the
# library can actually meet, and aborts with RSZ-0090. That abort is
# reached from global_placement -timing_driven (gpl -> TimingBase ->
# findResizeSlacks -> RepairDesign -> checkSlewLimit), NOT only from
# an explicit repair_design — hence this runs first.
# Measured here: buffer family n=28, measured area span 10.33X, leakage span 0X, margin x1.1; OpenROAD default 4X.
# max_transition is NOT modified; only the cell pool is restored.
if {[catch {set_opt_config -limit_sizing_area 11.37} _sl_e]} {
  puts "SIZING_LIMITS_NONFATAL: $_sl_e"
} else {
  puts "SIZING_LIMITS_APPLIED: -limit_sizing_area 11.37 (buffer family n=28, measured area span 10.33X, leakage span 0X, margin x1.1; OpenROAD default 4X)"
}
# === v0.1.26 wire-RC model ===
# Without set_wire_rc, OpenROAD has no per-layer R/C, so (a) STA ignores
# interconnect delay (optimistic) and (b) repair_timing -setup aborts with
# RSZ-0089 "Could not find a resistance value for any corner" because it
# cannot evaluate max wire length for buffering. Set signal nets to a mid
# metal layer and clock nets to an upper layer (sky130 convention). The
# layer names are resolved against the loaded tech LEF; a NONFATAL note
# keeps the flow moving on PDKs whose layer names differ.
if {[catch {set_wire_rc -signal -layer Metal1} _swr_sig]} {
  if {[catch {set_wire_rc -layer Metal1} _swr_sig2]} {
    puts "SET_WIRE_RC_SIGNAL_NONFATAL: $_swr_sig2"
  }
}
if {[catch {set_wire_rc -clock -layer Metal5} _swr_clk]} {
  puts "SET_WIRE_RC_CLOCK_NONFATAL: $_swr_clk"
}
# <<<PNR_RESUME_ELIDE_BEGIN>>>
# Everything between this sentinel and PNR_RESUME_ELIDE_END BUILDS the routed
# database from the netlist. A resume replaces the whole region with a
# `read_def` of the last stage checkpoint, so the work is never redone.

puts "PROBE_STAGE: width_cap"
# === unplaceable-master width cap (measured from the LIVE tap grid) ===
# FIXED taps bound the longest contiguous free-site run in every row.
# A master wider than that bound has NO legal site at ANY utilization;
# if the resizer/CTS inserts one, detailed_placement can never legalize
# it and detailed_route then aborts DRT-0073 and writes a DEF with zero
# signal routing. Measure the bound, then forbid the masters above it
# BEFORE the first buffer is inserted.
if {[catch {
  set _wc_blk [ord::get_db_block]
  set _wc_rows [$_wc_blk getRows]
  if {[llength $_wc_rows] > 0} {
    set _wc_sw [[[lindex $_wc_rows 0] getSite] getWidth]
    array unset _wc_fx
    set _wc_nfixed 0
    foreach _wc_i [$_wc_blk getInsts] {
      set _wc_st [$_wc_i getPlacementStatus]
      if {$_wc_st ne "FIRM" && $_wc_st ne "LOCKED" && $_wc_st ne "FIXED"} { continue }
      set _wc_bb [$_wc_i getBBox]
      lappend _wc_fx([$_wc_bb yMin]) [list [$_wc_bb xMin] [$_wc_bb xMax]]
      incr _wc_nfixed
    }
    # #966: scan the ROWS, not the fixed-instance buckets. A row with
    # no fixed instance is a FULL-WIDTH free run -- usually the longest
    # on the die -- and bucket iteration never visited it, so the bound
    # came out too small and forbade masters that were placeable.
    # Each row is measured against its OWN extent and its OWN fixed set.
    set _wc_run 0
    foreach _wc_r $_wc_rows {
      set _wc_rb [$_wc_r getBBox]
      set _wc_x0 [$_wc_rb xMin]
      set _wc_x1 [$_wc_rb xMax]
      set _wc_y [$_wc_rb yMin]
      set _wc_own {}
      if {[info exists _wc_fx($_wc_y)]} { set _wc_own $_wc_fx($_wc_y) }
      set _wc_cur $_wc_x0
      foreach _wc_p [lsort -integer -index 0 $_wc_own] {
        set _wc_g [expr {[lindex $_wc_p 0] - $_wc_cur}]
        if {$_wc_g > $_wc_run} { set _wc_run $_wc_g }
        if {[lindex $_wc_p 1] > $_wc_cur} { set _wc_cur [lindex $_wc_p 1] }
      }
      set _wc_g [expr {$_wc_x1 - $_wc_cur}]
      if {$_wc_g > $_wc_run} { set _wc_run $_wc_g }
    }
    puts "PLACEABLE_WIDTH_BOUND: $_wc_run dbu = [expr {$_wc_run / $_wc_sw}] site(s); fixed obstructions=$_wc_nfixed; rows=[llength $_wc_rows]"
    set _wc_kill {}
    set _wc_keepbuf 0
    if {$_wc_run > 0} {
      foreach _wc_lib [[ord::get_db] getLibs] {
        foreach _wc_m [$_wc_lib getMasters] {
          if {![$_wc_m isCore]} { continue }
          if {[$_wc_m getWidth] > $_wc_run} { lappend _wc_kill [$_wc_m getName] }
        }
      }
      # GUARD: never take away the last usable buffer.
      foreach _wc_c [get_lib_cells -quiet *] {
        if {[catch {set _wc_ib [get_property $_wc_c is_buffer]}]} { continue }
        if {!$_wc_ib} { continue }
        if {[catch {set _wc_du [get_property $_wc_c dont_use]}]} { set _wc_du 0 }
        if {$_wc_du} { continue }
        if {[lsearch -exact $_wc_kill [get_name $_wc_c]] >= 0} { continue }
        incr _wc_keepbuf
      }
    }
    # GUARD: a non-positive bound is a broken floorplan, not a library
    # problem -- forbidding every master cannot give it free space.
    if {$_wc_run <= 0} {
      puts "UNPLACEABLE_MASTERS_SKIPPED: measured free-site run is $_wc_run dbu -- no row has free space; excluding masters cannot create any -- left enabled"
    } elseif {[llength $_wc_kill] == 0} {
      puts "UNPLACEABLE_MASTERS_NONE: every core master fits the measured free-site run"
    } elseif {$_wc_keepbuf < 1} {
      puts "UNPLACEABLE_MASTERS_SKIPPED: excluding [llength $_wc_kill] master(s) would empty the buffer pool (survivors=$_wc_keepbuf) -- left enabled"
    } else {
      set _wc_n 0
      foreach _wc_nm $_wc_kill {
        set _wc_lc [get_lib_cells -quiet $_wc_nm]
        if {[llength $_wc_lc] == 0} { continue }
        if {[catch {set_dont_use $_wc_lc}]} { continue }
        incr _wc_n
      }
      puts "UNPLACEABLE_MASTERS_EXCLUDED: $_wc_n master(s) wider than [expr {$_wc_run / $_wc_sw}] site(s); buffers still usable=$_wc_keepbuf -- $_wc_kill"
    }
    # REPORT-ONLY: masters the netlist already instantiates that the
    # floorplan cannot legalize. set_dont_use cannot undo those.
    set _wc_pre {}
    if {$_wc_run > 0} {
      foreach _wc_i [$_wc_blk getInsts] {
        if {[[$_wc_i getMaster] getWidth] > $_wc_run} {
          lappend _wc_pre [$_wc_i getName]
        }
      }
    }
    if {[llength $_wc_pre] > 0} {
      puts "UNPLACEABLE_INSTANCES_PRESENT: [llength $_wc_pre] instance(s) already in the netlist exceed the bound -- $_wc_pre"
    }
  }
} _wc_err]} { puts "UNPLACEABLE_MASTERS_NONFATAL: $_wc_err" }


puts "PROBE_STAGE: estimate_parasitics"
if {[catch {estimate_parasitics -placement} _pe_pl]} {
  puts "EST_PARASITICS_PLACEMENT_NONFATAL: $_pe_pl"
}

puts "PROBE_STAGE: cts"
if {[catch {clock_tree_synthesis -buf_list {gf180mcu_fd_sc_mcu7t5v0__clkbuf_4} -root_buf {gf180mcu_fd_sc_mcu7t5v0__clkbuf_16}} _e]} { puts "CTS_NONFATAL: $_e" }

puts "PROBE_STAGE: census"
set _blk [ord::get_db_block]
set _u [[[ord::get_db] getTech] getDbUnitsPerMicron]
array unset _c ; array unset _w
foreach _in [$_blk getInsts] {
  set _m [$_in getMaster] ; set _n [$_m getName]
  if {[string match {*__clkbuf_*} $_n]} {
    if {[info exists _c($_n)]} { incr _c($_n) } else { set _c($_n) 1 }
    set _w($_n) [$_m getWidth]
  }
}
set _tot 0 ; set _atbound 0
foreach _n [lsort [array names _c]] {
  set _sw [expr {double($_w($_n))/$_u/0.56}]
  puts [format "CENSUS %-46s n=%-7d %8.3f um = %5.1f site(s)" $_n $_c($_n) [expr {double($_w($_n))/$_u}] $_sw]
  incr _tot $_c($_n)
  if {$_sw >= 50.0} { incr _atbound $_c($_n) }
}
puts "CENSUS_TOTAL clkbuf instances=$_tot at-or-over-50-sites=$_atbound"
puts "PROBE_DONE baseline"
