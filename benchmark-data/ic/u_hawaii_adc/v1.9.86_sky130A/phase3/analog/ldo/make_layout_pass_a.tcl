drc off
snap internal
load scratch_dev_nfet_w16_l1 -silent
box values 0 0 0 0
magic::gencell sky130::sky130_fd_pr__nfet_01v8 i_dev_nfet_w16_l1 w 16 l 1 nf 1 m 1
set cd [instance list celldef i_dev_nfet_w16_l1]
cellname rename $cd dev_nfet_w16_l1
load scratch_dev_nfet_w20_l0p5 -silent
box values 0 0 0 0
magic::gencell sky130::sky130_fd_pr__nfet_01v8 i_dev_nfet_w20_l0p5 w 20 l 0.5 nf 1 m 1
set cd [instance list celldef i_dev_nfet_w20_l0p5]
cellname rename $cd dev_nfet_w20_l0p5
load scratch_dev_pfet_w20_l0p5 -silent
box values 0 0 0 0
magic::gencell sky130::sky130_fd_pr__pfet_01v8 i_dev_pfet_w20_l0p5 w 20 l 0.5 nf 1 m 1
set cd [instance list celldef i_dev_pfet_w20_l0p5]
cellname rename $cd dev_pfet_w20_l0p5
load scratch_dev_pfet_w60_l0p15 -silent
box values 0 0 0 0
magic::gencell sky130::sky130_fd_pr__pfet_01v8 i_dev_pfet_w60_l0p15 w 60 l 0.15 nf 1 m 1
set cd [instance list celldef i_dev_pfet_w60_l0p15]
cellname rename $cd dev_pfet_w60_l0p15
load scratch_cap_cap_mim_m3_1_w27p5_l27p5 -silent
box values 0 0 0 0
magic::gencell sky130::sky130_fd_pr__cap_mim_m3_1 i_cap_cap_mim_m3_1_w27p5_l27p5 w 27.5 l 27.5 nx 1 ny 1
set cd [instance list celldef i_cap_cap_mim_m3_1_w27p5_l27p5]
cellname rename $cd cap_cap_mim_m3_1_w27p5_l27p5
load scratch_res_res_high_po_1p41_w1p41_l440p9 -silent
box values 0 0 0 0
magic::gencell sky130::sky130_fd_pr__res_high_po_1p41 i_res_res_high_po_1p41_w1p41_l440p9 w 1.41 l 440.9 nx 1
set cd [instance list celldef i_res_res_high_po_1p41_w1p41_l440p9]
cellname rename $cd res_res_high_po_1p41_w1p41_l440p9
writeall force
quit -noprompt
