drc off
snap internal
load scratch_dev_nfet_w16_l1 -silent
box values 0 0 0 0
magic::gencell sky130::sky130_fd_pr__nfet_01v8 i_dev_nfet_w16_l1 w 16 l 1 nf 1 m 1
set cd [instance list celldef i_dev_nfet_w16_l1]
cellname rename $cd dev_nfet_w16_l1
load scratch_dev_nfet_w32_l2 -silent
box values 0 0 0 0
magic::gencell sky130::sky130_fd_pr__nfet_01v8 i_dev_nfet_w32_l2 w 32 l 2 nf 1 m 1
set cd [instance list celldef i_dev_nfet_w32_l2]
cellname rename $cd dev_nfet_w32_l2
load scratch_dev_pfet_w32_l2 -silent
box values 0 0 0 0
magic::gencell sky130::sky130_fd_pr__pfet_01v8 i_dev_pfet_w32_l2 w 32 l 2 nf 1 m 1
set cd [instance list celldef i_dev_pfet_w32_l2]
cellname rename $cd dev_pfet_w32_l2
writeall force
quit -noprompt
