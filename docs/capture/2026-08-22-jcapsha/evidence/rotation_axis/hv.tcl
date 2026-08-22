# One process per (rotation_horizontal, rotation_vertical) pair.
# Question: does -rotation_horizontal control the HORIZONTAL rows, and
#           -rotation_vertical the VERTICAL rows, as the flag names say?
set rh $::env(ROTH)
set rv $::env(ROTV)
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef
foreach f [glob /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_io/lef/*.lef] { read_lef $f }
make_fake_io_site -name GF_IO_Site  -width 0.1 -height 355
make_fake_io_site -name GF_COR_Site -width 355 -height 355
# The probe writes its OWN input, so this directory tracks no tool output and
# the reproduction needs nothing but this file. Four unplaced instances, one
# per side, on a square die.
set defpath "/tmp/jcapsha_probe.def"
set fh [open $defpath w]
puts $fh "VERSION 5.8 ;"
puts $fh {DIVIDERCHAR "/" ;}
puts $fh {BUSBITCHARS "[]" ;}
puts $fh "DESIGN probe ;"
puts $fh "UNITS DISTANCE MICRONS 1000 ;"
puts $fh "DIEAREA ( 0 0 ) ( 2262000 2262000 ) ;"
puts $fh "COMPONENTS 4 ;"
puts $fh "- ps0 gf180mcu_fd_io__bi_t + UNPLACED ;"
puts $fh "- pn0 gf180mcu_fd_io__bi_t + UNPLACED ;"
puts $fh "- pw0 gf180mcu_fd_io__bi_t + UNPLACED ;"
puts $fh "- pe0 gf180mcu_fd_io__bi_t + UNPLACED ;"
puts $fh "END COMPONENTS"
puts $fh "END DESIGN"
close $fh
read_def $defpath
make_io_sites -horizontal_site GF_IO_Site -vertical_site GF_IO_Site \
  -corner_site GF_COR_Site -offset 26 \
  -rotation_horizontal $rh -rotation_vertical $rv -rotation_corner R0
place_pad -row IO_SOUTH -location 500 ps0 -master gf180mcu_fd_io__bi_t
place_pad -row IO_NORTH -location 500 pn0 -master gf180mcu_fd_io__bi_t
place_pad -row IO_WEST  -location 500 pw0 -master gf180mcu_fd_io__bi_t
place_pad -row IO_EAST  -location 500 pe0 -master gf180mcu_fd_io__bi_t
set b [ord::get_db_block]
set u [[ord::get_db_tech] getDbUnitsPerMicron]
puts "##### ROTH=$rh ROTV=$rv"
puts "  ROWS:"
foreach r [$b getRows] {
  puts "    [$r getName] orient=[[$r getSite] getName]/[$r getOrient]"
}
puts "  PADS:"
foreach n {ps0 pn0 pw0 pe0} {
  set i [$b findInst $n]; set bb [$i getBBox]
  puts "    $n orient=[$i getOrient] dx=[expr ([$bb xMax]-[$bb xMin])/double($u)] dy=[expr ([$bb yMax]-[$bb yMin])/double($u)]"
}
exit 0
