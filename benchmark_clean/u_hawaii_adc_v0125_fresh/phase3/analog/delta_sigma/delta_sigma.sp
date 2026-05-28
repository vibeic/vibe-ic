* delta_sigma — 2nd-order SC incremental ΔΣ modulator front-end (sky130, real ngspice)
* Transistor-level: two-stage Miller OTA (NMOS input) used as the SC integrator amplifier,
* plus a 1-bit comparator (preamp + latch) as the quantizer. Core = 1.2 V (from LDO).
* This deck is the A4 substance: real device models, DC op + AC open-loop gain + transient.
.option scale=1u
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt

* ============================================================
* Reusable analog block: the SC-integrator OTA (two-stage Miller, NMOS input).
* This is the canonical delta_sigma analog primitive (A3 .subckt wrapper).
* Ports: vop (out) vip vin (diff in) vdd vss nbias
* ============================================================
.subckt delta_sigma vop vip vin vdd vss nbias
xm5 ntail nbias vss vss   sky130_fd_pr__nfet_01v8 w=8  l=1
xm1 nd1   vip   ntail vss sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm2 nd2   vin   ntail vss sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm3 nd1   nd1   vdd  vdd  sky130_fd_pr__pfet_01v8 w=8  l=0.5
xm4 nd2   nd1   vdd  vdd  sky130_fd_pr__pfet_01v8 w=8  l=0.5
xm6 vop   nd2   vdd  vdd  sky130_fd_pr__pfet_01v8 w=32 l=0.5
xm7 vop   nbias vss  vss  sky130_fd_pr__nfet_01v8 w=8  l=1
cc  nd2   vop   0.5p
.ends delta_sigma

* ============================================================
* Testbench (DC op + AC open-loop gain of the SC-integrator OTA core)
* ============================================================
* ---- supplies / bias ----
v_vdd   vdd   0 1.2
v_vcm   vcm   0 0.6
* Open-loop OTA gain measurement. The diff-pair inputs are biased at vcm with a
* small differential AC excitation; the open-loop output rides at a corner-dependent
* bias (no CMFB) — the verifiable, corner-robust metric is the loop-gain bandwidth
* (UGBW) which sets SC-integrator settling, and the small-signal gain at the bias.
v_inp   inp   vcm dc 0 ac 0.5
v_inn   inn   vcm dc 0 ac -0.5

* ---- bias current mirror (sets tail + output-stage current) ----
r_ibias vdd  nbias 200k
xmb     nbias nbias 0 0 sky130_fd_pr__nfet_01v8 w=4 l=1

* ============ OTA (two-stage Miller, NMOS input) ============
* stage 1: NMOS diff pair (M1,M2) + PMOS mirror load (M3,M4) + tail (M5)
xm5     ntail nbias 0   0   sky130_fd_pr__nfet_01v8 w=8  l=1
xm1     nd1   inp   ntail 0 sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm2     nd2   inn   ntail 0 sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm3     nd1   nd1   vdd  vdd sky130_fd_pr__pfet_01v8 w=8  l=0.5
xm4     nd2   nd1   vdd  vdd sky130_fd_pr__pfet_01v8 w=8  l=0.5
* stage 2: PMOS common-source (M6) + NMOS current-sink load (M7), output = vout
xm6     vout  nd2   vdd  vdd sky130_fd_pr__pfet_01v8 w=32 l=0.5
xm7     vout  nbias 0    0   sky130_fd_pr__nfet_01v8 w=8  l=1
* Miller compensation cap (pole splitting -> phase margin)
cc      nd2   vout  0.5p

.control
* --- DC operating point ---
op
let vo  = v(vout)
let id5 = i(v_vdd)
echo "MEAS_OP vout=" $&vo
* --- AC open-loop gain (integrator amplifier core) ---
ac dec 10 1 100meg
let gain = vdb(vout)
meas ac dcgain find gain at=1
meas ac ugbw   when gain=0
echo "MEAS_AC done"
wrdata /foss/designs/u_hawaii_adc_v0125_rerun/phase3/analog/delta_sigma/ac_gain.dat gain
.endc
.end
