set rot $::env(ROTH)
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef
foreach f [glob /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_io/lef/*.lef] { read_lef $f }
make_fake_io_site -name GF_IO_Site  -width 0.1 -height 355
make_fake_io_site -name GF_COR_Site -width 355 -height 355
read_def /w/probe.def
make_io_sites -horizontal_site GF_IO_Site -vertical_site GF_IO_Site \
  -corner_site GF_COR_Site -offset 26 \
  -rotation_horizontal $rot -rotation_vertical R0 -rotation_corner R0
place_pad -row IO_WEST  -location 500 pw0 -master gf180mcu_fd_io__bi_t
place_pad -row IO_EAST  -location 500 pw1 -master gf180mcu_fd_io__bi_t
place_pad -row IO_SOUTH -location 500 ps0 -master gf180mcu_fd_io__bi_t
set b [ord::get_db_block]
set u [[ord::get_db_tech] getDbUnitsPerMicron]
puts "##### rotation_horizontal=$rot dbu/um=$u"
foreach n {pw0 pw1 ps0} {
  set i [$b findInst $n]; set bb [$i getBBox]
  puts "  $n orient=[$i getOrient] along/into(um): dx=[expr ([$bb xMax]-[$bb xMin])/double($u)] dy=[expr ([$bb yMax]-[$bb yMin])/double($u)]"
}
exit 0
