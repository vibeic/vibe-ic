set layout  /foss/designs/mdio_phase1_p3/phase3/stage3/lvs/chip_top.spice
set source  /foss/designs/mdio_phase1_p3/phase3/stage3/pnr/chip_top_pnr.v
set setup   /foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl
lvs "$layout chip_top" "$source chip_top" $setup /foss/designs/mdio_phase1_p3/phase3/stage3/lvs/lvs.report -json
