* delta_sigma.sp — incremental delta-sigma modulator integrator block (analog-netlist-gen)
* pdk_substitution: target=sg13g2 substitute=sky130 reason=no public ngspice models for target
* Topology: 2nd-order single-loop SC incremental modulator; the transistor-level cell is the
* integrator OTA (two-stage Miller, NMOS-input) with the SC sampling/integrating cap network.
* Device sizes are the sized point from the analog sizing loop (Cs=0.25-0.5 pF, Ci=1 pF).
* Ports: vdd (core 1.2V) vss vcm (0.6V common-mode ref) vin (sampled input) vout (integrator out)
.subckt delta_sigma vdd vss vcm vin vout
* --- bias current mirror ---
r_ib vdd nbias 200k
xmb  nbias nbias vss vss sky130_fd_pr__nfet_01v8 w=4 l=1
* --- two-stage Miller OTA: NMOS-input first stage, PMOS-load ---
xm5 ntail nbias vss vss   sky130_fd_pr__nfet_01v8 w=8  l=1
xm1 nd1 vsum ntail vss     sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm2 nd2 vcm  ntail vss     sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm3 nd1 nd1 vdd vdd        sky130_fd_pr__pfet_01v8 w=8  l=0.5
xm4 nd2 nd1 vdd vdd        sky130_fd_pr__pfet_01v8 w=8  l=0.5
* --- second stage: PMOS common-source + NMOS current-source load ---
xm6 vout nd2 vdd vdd       sky130_fd_pr__pfet_01v8 w=32 l=0.5
xm7 vout nbias vss vss     sky130_fd_pr__nfet_01v8 w=8  l=1
* --- Miller compensation ---
cc  nd2 vout 0.5p
* --- switched-capacitor integrator network (Cs into virtual ground, Ci in feedback) ---
cs  vin  vsum 0.25p
ci  vsum vout 1p
.ends delta_sigma
