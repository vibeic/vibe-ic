# Magic GDS -> SPICE extraction for LVS (sky130A)
gds read /foss/designs/espi_phase3_stage/phase3/stage3/pnr/chip_top.gds
load chip_top
select top cell
extract all
ext2spice lvs
ext2spice -o /foss/designs/espi_phase3_stage/phase3/stage3/lvs/chip_top_layout.spice
quit -noprompt
