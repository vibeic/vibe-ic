* esd ESD diode clamp — measure Vfwd at 1mA forward.
.option scale=1u
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt
v_inj pad 0 0.7
i_test pad 0 dc 1m
* Forward diode = diode-connected NMOS in deep saturation
xmn_diode pad pad 0 0 sky130_fd_pr__nfet_01v8 w=10 l=0.5
.control
op
let vo = v(pad)
echo "MEAS vout=" $&vo
.endc
.end
