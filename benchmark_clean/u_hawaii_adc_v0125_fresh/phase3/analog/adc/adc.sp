* adc — incremental-ΔΣ ADC analog front-end (sky130, real ngspice)
* Analog content = the modulator front-end OTA (SC integrator amplifier). The decimation
* counter / serial read-out is DIGITAL (out of analog scope per L5). Same two-stage Miller
* NMOS-input OTA core as delta_sigma. Core = 1.2 V (from LDO). DC op + AC open-loop gain.
.option scale=1u
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt

* ============================================================
* Reusable analog block: the ADC front-end OTA (SC-integrator amplifier,
* two-stage Miller NMOS-input). Canonical adc analog primitive (A3 .subckt wrapper).
* Ports: vop (out) vip vin (diff in) vdd vss nbias
* ============================================================
.subckt adc vop vip vin vdd vss nbias
xm5 ntail nbias vss vss   sky130_fd_pr__nfet_01v8 w=8  l=1
xm1 nd1   vip   ntail vss sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm2 nd2   vin   ntail vss sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm3 nd1   nd1   vdd  vdd  sky130_fd_pr__pfet_01v8 w=8  l=0.5
xm4 nd2   nd1   vdd  vdd  sky130_fd_pr__pfet_01v8 w=8  l=0.5
xm6 vop   nd2   vdd  vdd  sky130_fd_pr__pfet_01v8 w=32 l=0.5
xm7 vop   nbias vss  vss  sky130_fd_pr__nfet_01v8 w=8  l=1
cc  nd2   vop   0.5p
.ends adc

* ============================================================
* Testbench (DC op + AC open-loop gain of the front-end OTA core)
* ============================================================
v_vdd vdd 0 1.2
v_vcm vcm 0 0.6
v_inp inp vcm dc 0 ac 0.5
v_inn inn vcm dc 0 ac -0.5

r_ibias vdd nbias 200k
xmb nbias nbias 0 0 sky130_fd_pr__nfet_01v8 w=4 l=1

* front-end OTA (two-stage Miller, NMOS input)
xm5 ntail nbias 0   0   sky130_fd_pr__nfet_01v8 w=8  l=1
xm1 nd1   inp   ntail 0 sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm2 nd2   inn   ntail 0 sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm3 nd1   nd1   vdd  vdd sky130_fd_pr__pfet_01v8 w=8  l=0.5
xm4 nd2   nd1   vdd  vdd sky130_fd_pr__pfet_01v8 w=8  l=0.5
xm6 vout  nd2   vdd  vdd sky130_fd_pr__pfet_01v8 w=32 l=0.5
xm7 vout  nbias 0    0   sky130_fd_pr__nfet_01v8 w=8  l=1
cc  nd2   vout  0.5p

.control
op
let vo = v(vout)
echo "MEAS_OP vout=" $&vo
ac dec 10 1 100meg
let gain = vdb(vout)
meas ac dcgain find gain at=1
meas ac ugbw   when gain=0
echo "MEAS_AC done"
wrdata /foss/designs/u_hawaii_adc_v0125_rerun/phase3/analog/adc/ac_gain.dat gain
.endc
.end
