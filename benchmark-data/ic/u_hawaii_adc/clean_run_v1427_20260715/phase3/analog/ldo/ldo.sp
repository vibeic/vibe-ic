* ldo — LDO SPICE subckt (analog-netlist-gen). Device roles are PDK-family-agnostic
* placeholders (nmos/pmos) resolved to the staged PDK device map at sim time.
.subckt ldo vdd vref vout
xmn_b    nbias nbias 0    0   nmos_dev w=2 l=2
r_ibias  vdd   nbias      600k
xmp_pass vout  vg    vdd  vdd pmos_dev w=5 l=0.5 m=80
xmn_tail ntail nbias 0    0   nmos_dev w=4 l=2
xmn1     nd1   vfb   ntail 0  nmos_dev w=8 l=1
xmn2     vg    vref  ntail 0  nmos_dev w=8 l=1
xmp1     nd1   nd1   vdd  vdd pmos_dev w=4 l=1
xmp2     vg    nd1   vdd  vdd pmos_dev w=4 l=1
cc       vg    vout       5p
r1       vout  vfb        8k
r2       vfb   0          8k
.ends ldo
