gds read /foss/designs/mdio_phase1_p3/phase3/stage3/pnr/chip_top.gds
load chip_top
select top cell
extract all
ext2spice lvs
ext2spice -o /foss/designs/mdio_phase1_p3/phase3/stage3/lvs/chip_top.spice
quit -noprompt
