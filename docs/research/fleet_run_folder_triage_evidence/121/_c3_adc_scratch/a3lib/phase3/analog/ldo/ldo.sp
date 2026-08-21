* ldo — A3 netlist deliverable (subckt definition library)
.subckt ldo vin_io vref vout vss
xmp_pass vout vg vin_io vin_io sg13_hv_pmos w=80u l=0.5u m=1
xmn_in1  nd1  vref ntail vss  sg13_hv_nmos w=10u l=0.5u m=1
xmn_in2  vg   vfb  ntail vss  sg13_hv_nmos w=10u l=0.5u m=1
xr1 vout vfb  bn rhigh w=1u l=50u
xr2 vfb  vss  bn rhigh w=1u l=50u
xc1 vg vout cap_cmim w=10u l=10u
.ends
