# Which rows does -horizontal_site land in?  Two DISTINCT sites, so the row
# report names which flag fed it.  This is the positive control for the
# meaning of the word "horizontal" in this command's own flag names.
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef
foreach f [glob /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_io/lef/*.lef] { read_lef $f }
make_fake_io_site -name SITE_FED_TO_HORIZONTAL_FLAG -width 0.1 -height 355
make_fake_io_site -name SITE_FED_TO_VERTICAL_FLAG   -width 0.1 -height 355
make_fake_io_site -name GF_COR_Site -width 355 -height 355
read_def /w/probe.def
make_io_sites -horizontal_site SITE_FED_TO_HORIZONTAL_FLAG \
  -vertical_site SITE_FED_TO_VERTICAL_FLAG \
  -corner_site GF_COR_Site -offset 26 \
  -rotation_horizontal R0 -rotation_vertical R0 -rotation_corner R0
set b [ord::get_db_block]
foreach r [$b getRows] { puts "    [$r getName]  site=[[$r getSite] getName]" }
exit 0
