# DEF-based extraction preserves net/pin names for LVS
lef read /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
lef read /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef
def read /foss/designs/espi_phase3_stage/phase3/stage3/pnr/routed.def
load chip_top
select top cell
extract no all
extract do local
extract unique
extract
ext2spice lvs
ext2spice -o /foss/designs/espi_phase3_stage/phase3/stage3/lvs/chip_top_def.spice
quit -noprompt
