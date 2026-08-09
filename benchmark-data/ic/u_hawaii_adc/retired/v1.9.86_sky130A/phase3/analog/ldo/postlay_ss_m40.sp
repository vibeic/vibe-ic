* post-layout re-simulation (A7) -- extracted from the routed LVS-clean layout
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice ss
.include ldo_rc.spice
.temp -40
Viovdd IOVDD 0 DC 1.8 AC 1
Vref   VREF  0 0.6
Vbias  VBIAS 0 0.8
Cl     VOUT  0 20p
Iload  VOUT  0 0.5m
Xdut IOVDD VREF VOUT VBIAS 0 ldo
.control
dc Viovdd 1.6 2.0 0.05
meas dc vout FIND v(VOUT) AT=1.8
ac dec 10 1 1e6
meas ac psrr FIND vdb(VOUT) AT=100
.endc
.end
