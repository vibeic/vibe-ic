* delta_sigma — 2nd-order incremental delta-sigma modulator (analog-netlist-gen).
* Structural device-level subckt: two SC integrators (OTA-based) + 1-bit comparator
* + 1-bit feedback DAC. Device roles are PDK-family-agnostic placeholders
* (nmos/pmos) resolved to the staged PDK device map at sim time. A full transient
* SNDR/ENOB sweep requires a native SC-modulator .tran template (A4 has no DC
* template for this block_type — corner sweep is WAIVED, not faked).
.subckt ota inp inn out vdd vss
xmn1  nd1 inp ntail vss nmos_dev w=8 l=1
xmn2  out inn ntail vss nmos_dev w=8 l=1
xmp1  nd1 nd1 vdd  vdd pmos_dev w=4 l=1
xmp2  out nd1 vdd  vdd pmos_dev w=4 l=1
xmnt  ntail vb vss vss nmos_dev w=16 l=1
.ends ota

.subckt delta_sigma vin vref vdd vss ck dout
* integrator 1
cs1  vin  n1        0.5p
ci1  n1   vo1       1p
xota1 n1  vcm vo1   vdd vss ota
* integrator 2
cs2  vo1  n2        0.5p
ci2  n2   vo2       1p
xota2 n2  vcm vo2   vdd vss ota
* 1-bit comparator (quantizer) — behavioral clocked latch node
xcmp  vo2 vcm dout  vdd vss ota
* 1-bit feedback DAC to input summing node
cfb  dout n1        0.5p
.ends delta_sigma
