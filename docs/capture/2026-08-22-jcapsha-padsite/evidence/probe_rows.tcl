read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef
foreach f [glob /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_io/lef/*.lef] { read_lef $f }
make_fake_io_site -name H_SITE -width 0.1 -height 355
make_fake_io_site -name V_SITE -width 0.2 -height 355
make_fake_io_site -name GF_COR_Site -width 355 -height 355
read_def /w/probe.def
make_io_sites -horizontal_site H_SITE -vertical_site V_SITE \
  -corner_site GF_COR_Site -offset 26 \
  -rotation_horizontal $::env(ROTH) -rotation_vertical $::env(ROTV) -rotation_corner R0
set b [ord::get_db_block]
puts "##### ROTH=$::env(ROTH) ROTV=$::env(ROTV)"
foreach row [$b getRows] {
  puts "  row=[$row getName] site=[[$row getSite] getName] orient=[$row getOrient]"
}
exit 0
