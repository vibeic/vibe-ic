* MC iteration 6/30 — analog_mc_yield_run (foundry statistical section 'mc')
.option seed=6
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice mc
* ldo.sp — LDO reusable analog block netlist (analog-netlist-gen)
* pdk_substitution: target=sg13g2 substitute=sky130 reason=no public ngspice models for target
* Topology: PMOS-pass, NMOS-input two-stage error amplifier LDO (see topology.md).
* Device sizes are the sized point from the analog sizing loop (m_pass=160, Vout=1.19913 V).
* Ports: vdd (IOVDD 1.8V) vss vref (0.6V) vout (regulated 1.2V CORE)
.subckt ldo vdd vss vref vout
* --- bias current mirror leg (sets tail current) ---
xmn_b   nbias nbias vss vss sky130_fd_pr__nfet_01v8 w=2 l=2
r_ibias vdd   nbias 600k
* --- error amplifier: NMOS diff pair + PMOS current-mirror load ---
xmn_tail ntail nbias vss vss sky130_fd_pr__nfet_01v8 w=4 l=2
xmn1     nd1   vfb   ntail vss sky130_fd_pr__nfet_01v8 w=8 l=1
xmn2     vg    vref  ntail vss sky130_fd_pr__nfet_01v8 w=8 l=1
xmp1     nd1   nd1   vdd   vdd sky130_fd_pr__pfet_01v8 w=4 l=1
xmp2     vg    nd1   vdd   vdd sky130_fd_pr__pfet_01v8 w=4 l=1
* --- PMOS series-pass device (sized by multiplier) ---
xmp_pass vout  vg    vdd   vdd sky130_fd_pr__pfet_01v8 w=5 l=0.5 m=160
* --- Miller compensation + resistive feedback divider (Vout = 2*Vref) ---
cc  vg   vout 5p
r1  vout vfb  8k
r2  vfb  vss  8k
.ends ldo

