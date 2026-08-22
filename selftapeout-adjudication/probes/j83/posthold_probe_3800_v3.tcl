# J83 POST-HOLD PROBE -- the runner's own pnr.tcl.  Setup 1..9 and 14..137
# verbatim, DEF entry instead of read_verilog+link_design, then 8302..8317
# (hold repair + ladder rungs 1-4) and 8325..8347 (the clkswap rung).
# The FULL-DIE rung 8318..8324 is deliberately ABSENT: five arms are inside
# it and this probe must not become a sixth.


set_thread_count 32
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lef/gf180mcu_fd_sc_mcu7t5v0.lef

define_corners ss tt ff
read_liberty -corner ss /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__ss_125C_4v50.lib
read_liberty -corner tt /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib
read_liberty -corner ff /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__ff_n40C_5v50.lib

puts "PROBE_STAGE: read_def"
read_def /home/reyerchu/_jself_priv/proj/matmul_d3800/phase3/stage3/pnr/post_cts.def

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

puts "PROBE_STAGE: entry_control"
report_design_area


puts "PROBE_STAGE: propagate_clock"
if {[catch {set_propagated_clock [all_clocks]} _spc_e]} {
  puts "PROPAGATE_CLOCK_NONFATAL: $_spc_e"
}

puts "PROBE_STAGE: estimate_parasitics"
if {[catch {estimate_parasitics -placement} _pe_pl]} {
  puts "EST_PARASITICS_PLACEMENT_NONFATAL: $_pe_pl"
}
puts "PNR_STAGE: hold_repair"
if {[catch {repair_timing -hold} hold_err]} {
  puts "HOLD_NONFATAL: $hold_err"
}
set _dplok_ph 0
if {![catch {detailed_placement} _dpl_ph]} {
  if {![catch {check_placement} _cpk_ph]} { set _dplok_ph 1 ; puts "POST_HOLD_LEGALIZE_OK disp=default" }
}
if {$_dplok_ph == 0} {
  foreach _d_ph {5 20 100} {
    if {$_dplok_ph != 0} { break }
    if {[catch {detailed_placement -max_displacement $_d_ph} _dpl_ph]} { continue }
    if {![catch {check_placement} _cpk_ph]} { set _dplok_ph 1 ; puts "POST_HOLD_LEGALIZE_OK disp=$_d_ph" }
  }
}
puts "PROBE_PRESWAP_OK=$_dplok_ph"

puts "PROBE_STAGE: clkswap"
if {$_dplok_ph == 0} {
  if {![catch {
    set _rblk_ph [ord::get_db_block]
    set _rtgt_ph [[ord::get_db] findMaster gf180mcu_fd_sc_mcu7t5v0__clkbuf_4]
    if {$_rtgt_ph ne "NULL" && $_rtgt_ph ne ""} {
      set _rtw_ph [$_rtgt_ph getWidth]
      set _rn_ph 0
      foreach _rin_ph [$_rblk_ph getInsts] {
        set _rm_ph [$_rin_ph getMaster]
        if {[string match {*__clkbuf_*} [$_rm_ph getName]] && [$_rm_ph getWidth] > $_rtw_ph} {
          $_rin_ph swapMaster $_rtgt_ph; incr _rn_ph
        }
      }
      puts "POST_HOLD_CLKBUF_DOWNSIZE swapped=$_rn_ph -> gf180mcu_fd_sc_mcu7t5v0__clkbuf_4"
    }
  } _rec_ph]} { puts "POST_HOLD_CLKBUF_DOWNSIZE_NONFATAL: $_rec_ph" }
  if {![catch {detailed_placement} _dpl_ph]} {
    if {![catch {check_placement} _cpk_ph]} { set _dplok_ph 1 ; puts "POST_HOLD_LEGALIZE_OK disp=clkswap" }
  }
}
puts "PROBE_POSTSWAP_OK=$_dplok_ph"
puts "PROBE_DONE posthold_3800 (full-die rung deliberately NOT run)"
