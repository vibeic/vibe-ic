# Which ROWS does -horizontal_site land on, and which do -rotation_horizontal
# land on?  Two DISTINCT fake sites so the site argument is distinguishable.
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef
make_fake_io_site -name SITE_H -width 0.1 -height 355
make_fake_io_site -name SITE_V -width 0.2 -height 355
make_fake_io_site -name PROBE_COR -width 355 -height 355
read_def /w/probe.def
make_io_sites -horizontal_site SITE_H -vertical_site SITE_V \
    -corner_site PROBE_COR -offset 0 \
    -rotation_horizontal R90 -rotation_vertical R180 -rotation_corner R0
set block [[[ord::get_db] getChip] getBlock]
foreach n {IO_SOUTH IO_NORTH IO_EAST IO_WEST} {
    foreach row [$block getRows] {
        if {[$row getName] eq $n} {
            puts "ROW $n  site=[[$row getSite] getName]  orient=[$row getOrient]"
        }
    }
}
