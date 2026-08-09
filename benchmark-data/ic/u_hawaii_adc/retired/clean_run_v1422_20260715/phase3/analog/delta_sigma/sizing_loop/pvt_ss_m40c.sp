* pdk_substitution: target=sg13g2 substitute=sky130 reason=no public ngspice models for target; open-source substitute
* delta_sigma delta-sigma — 2nd-order SC integrator (two-stage Miller NMOS-input OTA),
* parametric sampling cap Cs, transient step settle + AC open-loop UGBW.
* DERIVED from u_hawaii_adc_v0125_rerun integrator_settle.sp + delta_sigma.sp (sky130).
.option scale=1u
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice ss
.param cs=0.25p
.param ci=1p
v_vdd vdd 0 1.2
v_vcm vcm 0 0.6
* input step at t=100ns: 0.6 -> 0.7 V applied through the sampling cap
v_in  vin 0 pwl(0 0.6  99n 0.6  101n 0.7  1000n 0.7)
* AC excitation on the same diff node for open-loop UGBW (dc 0 so it does not
* perturb the transient bias point; ngspice runs op/tran and ac independently)
* bias current mirror
r_ib vdd nbias 200k
xmb nbias nbias 0 0 sky130_fd_pr__nfet_01v8 w=4 l=1
* OTA: NMOS-input two-stage Miller. + input = vcm (ref), - input = vsum (virtual gnd)
xm5 ntail nbias 0 0     sky130_fd_pr__nfet_01v8 w=8  l=1
xm1 nd1 vsum ntail 0    sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm2 nd2 vcm  ntail 0    sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm3 nd1 nd1 vdd vdd     sky130_fd_pr__pfet_01v8 w=8  l=0.5
xm4 nd2 nd1 vdd vdd     sky130_fd_pr__pfet_01v8 w=8  l=0.5
xm6 vout nd2 vdd vdd    sky130_fd_pr__pfet_01v8 w=32 l=0.5
xm7 vout nbias 0 0      sky130_fd_pr__nfet_01v8 w=8  l=1
cc  nd2 vout 0.5p
* SC integrator network: sampling cap Cs into virtual ground, Ci in feedback
cs  vin  vsum 'cs'
ci  vsum vout 'ci'
* high-value bleeder to define DC bias of vsum node for ngspice op convergence
rbig vsum vcm 1g
.temp -40
.control
* transient: confirm OTA output integrates the input step within T/2 = 500 ns
tran 0.5n 1000n
meas tran vstep   find v(vout) at=100n
meas tran vsettle find v(vout) at=600n
let dv = vsettle - vstep
* AC open-loop UGBW of the integrator amplifier core (sets settling speed)
ac dec 10 1 100meg
let gain = vdb(vout)
meas ac dcgain find gain at=1
meas ac ugbw   when gain=0
echo "MEAS vout=" $&vsettle " vstep=" $&vstep " dv=" $&dv " ugbw=" $&ugbw " dcgain=" $&dcgain
.endc
.end
