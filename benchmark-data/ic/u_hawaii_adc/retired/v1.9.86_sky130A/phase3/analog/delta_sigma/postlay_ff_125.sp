* post-layout re-simulation (A7) -- extracted from the routed LVS-clean layout
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice ff
.include ds_ota_rc.spice
.temp 125
Vdd VDD 0 1.2
Vbias VBIAS 0 0.75
Vcm  CM 0 0.6
Vinp VINP CM AC 1
Lfb  VOUTA VINN 1T
Cbig VINN 0 1
Cl VOUTA 0 1p
Xdut VDD VINP VINN VOUTA VBIAS 0 ds_ota
.control
op
ac dec 10 1 1e8
meas ac dcgain FIND vdb(VOUTA) AT=1
.endc
.end
