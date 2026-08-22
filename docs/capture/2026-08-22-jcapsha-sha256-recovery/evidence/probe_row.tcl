set rotv $env(ROTV)
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef
make_fake_io_site -name PROBE_IO -width 0.1 -height 355
make_fake_io_site -name PROBE_COR -width 355 -height 355
read_def /w/probe.def
make_io_sites -horizontal_site PROBE_IO -vertical_site PROBE_IO \
    -corner_site PROBE_COR -offset 0 \
    -rotation_horizontal R0 -rotation_vertical $rotv -rotation_corner R0
set block [[[ord::get_db] getChip] getBlock]
foreach row [$block getRows] {
    puts "ROTV=$rotv ROW=[$row getName] orient=[$row getOrient] site=[[$row getSite] getName]"
}
