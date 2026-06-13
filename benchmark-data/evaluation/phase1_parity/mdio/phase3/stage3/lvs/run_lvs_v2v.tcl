set src1 /foss/designs/mdio_phase1_p3/phase2/stage2/synth/chip_top_synth.v
set src2 /foss/designs/mdio_phase1_p3/phase3/stage3/pnr/chip_top_pnr.v
set setup /foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl
lvs "$src1 chip_top" "$src2 chip_top" $setup /foss/designs/mdio_phase1_p3/phase3/stage3/lvs/lvs_v2v.report
