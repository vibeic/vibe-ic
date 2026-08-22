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
  if {$_dplok_ph == 0 && ![catch {ord::get_die_area} _da2_ph]} {
