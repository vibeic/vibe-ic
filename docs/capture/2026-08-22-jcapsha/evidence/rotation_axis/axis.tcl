# Which rows does -horizontal_site land in?  Two DISTINCT sites, so the row
# report names which flag fed it.  This is the positive control for the
# meaning of the word "horizontal" in this command's own flag names.
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef
foreach f [glob /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_io/lef/*.lef] { read_lef $f }
make_fake_io_site -name SITE_FED_TO_HORIZONTAL_FLAG -width 0.1 -height 355
make_fake_io_site -name SITE_FED_TO_VERTICAL_FLAG   -width 0.1 -height 355
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
make_io_sites -horizontal_site SITE_FED_TO_HORIZONTAL_FLAG \
  -vertical_site SITE_FED_TO_VERTICAL_FLAG \
  -corner_site GF_COR_Site -offset 26 \
  -rotation_horizontal R0 -rotation_vertical R0 -rotation_corner R0
set b [ord::get_db_block]
foreach r [$b getRows] { puts "    [$r getName]  site=[[$r getSite] getName]" }
exit 0
