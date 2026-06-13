set layout  /foss/designs/espi_phase3_stage/phase3/stage3/lvs/chip_top_layout.spice
set source  /foss/designs/espi_phase3_stage/phase3/stage3/lvs/chip_top_source.v
set setup   /foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl
lvs "$layout chip_top" "$source chip_top" $setup /foss/designs/espi_phase3_stage/phase3/stage3/lvs/lvs.report -json
