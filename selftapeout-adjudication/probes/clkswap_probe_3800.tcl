# J80 — the clkbuf-downsize rung, run as a CONTROLLED before/after on one artefact.
#
# Subject: the die-3800 arm's post_cts.def, written by the runner at 04:30 and closed.
# This is the POST-CTS state, NOT the post-hold state the five live arms are in, so it
# tests the MECHANISM behind J79's P1/P2/P3 and answers none of them.
#
# It runs ladder rungs 1-4 only (default / 5 / 20 / 100) and NEVER the full-die rung,
# so it cannot turn into another multi-hour arm.  Nothing is written into any project.

set_thread_count 8
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lef/gf180mcu_fd_sc_mcu7t5v0.lef

puts "PROBE_STAGE: read_def"
read_def /home/reyerchu/_jself_priv/proj/matmul_d3800/phase3/stage3/pnr/post_cts.def

# ---- census: reproduce J53's 2 055 root-master clock buffers from THIS DEF ----
puts "PROBE_STAGE: census"
set _blk [ord::get_db_block]
array set _cnt {}
array set _wid {}
foreach _in [$_blk getInsts] {
  set _mn [[$_in getMaster] getName]
  if {[string match {*__clkbuf_*} $_mn]} {
    if {[info exists _cnt($_mn)]} { incr _cnt($_mn) } else { set _cnt($_mn) 1 }
    set _wid($_mn) [[$_in getMaster] getWidth]
  }
}
set _dbu [[ord::get_db] getTech]
set _u [$_dbu getDbUnitsPerMicron]
set _tot 0.0
foreach _m [lsort [array names _cnt]] {
  set _w [expr {double($_wid($_m))/$_u}]
  puts [format "CENSUS %-46s n=%-7d width=%8.3f um" $_m $_cnt($_m) $_w]
}
puts "PROBE_STAGE: rungs_1_to_4"
set _ok 0
if {![catch {detailed_placement} _e]} {
  if {![catch {check_placement} _c]} { set _ok 1 ; puts "PROBE_LEGALIZE_OK rung=default" }
}
if {$_ok == 0} {
  foreach _d {5 20 100} {
    if {$_ok != 0} { break }
    if {[catch {detailed_placement -max_displacement $_d} _e]} { continue }
    if {![catch {check_placement} _c]} { set _ok 1 ; puts "PROBE_LEGALIZE_OK rung=$_d" }
  }
}
puts "PROBE_PRESWAP_OK=$_ok"

# ---- the FLOW'S OWN clkswap block, copied verbatim from pnr.tcl:8326-8340 ----
puts "PROBE_STAGE: clkswap"
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

puts "PROBE_STAGE: postswap_default"
set _ok2 0
if {![catch {detailed_placement} _e2]} {
  if {![catch {check_placement} _c2]} { set _ok2 1 ; puts "PROBE_LEGALIZE_OK rung=clkswap" }
}
puts "PROBE_POSTSWAP_OK=$_ok2"
puts "PROBE_DONE 3800 (full-die rung deliberately NOT run)"
