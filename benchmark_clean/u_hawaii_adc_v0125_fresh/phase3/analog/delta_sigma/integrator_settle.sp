* delta_sigma SC integrator settling — two-stage Miller OTA in inverting integrator config.
* A step is applied to the input cap; we confirm the OTA output settles within T/2 = 500 ns
* (fclk = 1 MHz -> half period 500 ns). sky130, core 1.2 V.
.option scale=1u
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt

v_vdd vdd 0 1.2
v_vcm vcm 0 0.6
* input step at t=100ns: 0.6 -> 0.7 V applied through the sampling cap
v_in  vin 0 pwl(0 0.6  99n 0.6  101n 0.7  1000n 0.7)

* bias
r_ib vdd nbias 200k
xmb nbias nbias 0 0 sky130_fd_pr__nfet_01v8 w=4 l=1

* OTA: NMOS-input two-stage Miller. + input = vcm (ref), - input = vsum (virtual ground)
xm5 ntail nbias 0 0     sky130_fd_pr__nfet_01v8 w=8  l=1
xm1 nd1 vsum ntail 0    sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm2 nd2 vcm  ntail 0    sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm3 nd1 nd1 vdd vdd     sky130_fd_pr__pfet_01v8 w=8  l=0.5
xm4 nd2 nd1 vdd vdd     sky130_fd_pr__pfet_01v8 w=8  l=0.5
xm6 vout nd2 vdd vdd    sky130_fd_pr__pfet_01v8 w=32 l=0.5
xm7 vout nbias 0 0      sky130_fd_pr__nfet_01v8 w=8  l=1
cc  nd2 vout 0.5p

* SC integrator network: sampling cap Cs into virtual ground, integrating cap Ci in feedback
cs  vin  vsum 0.5p
ci  vsum vout 1p
* high-value bleeder to define DC bias of vsum node for ngspice op convergence
rbig vsum vcm 1g

.control
tran 0.5n 1000n
meas tran vstep  find v(vout) at=100n
meas tran vsettle find v(vout) at=600n
let dv = vsettle - vstep
echo "MEAS_INT done"
wrdata /foss/designs/u_hawaii_adc_v0125_rerun/phase3/analog/delta_sigma/int_tran.dat v(vout) v(vin) v(vsum)
.endc
.end
