* tb_delta_sigma -- A4 delivered stimulus deck (OTA open-loop gain; sky130A substitute)
.include delta_sigma.sp
Vdd VDD 0 1.2
Vbias VBIAS 0 0.75
Vcm  CM 0 0.6
Vinp VINP CM AC 1
Lfb  VOUTA VINN 1T
Cbig VINN 0 1
Xdut VDD 0 VINP VINN VOUTA VBIAS ds_ota
Cl VOUTA 0 1p
.control
op
print v(VOUTA)
ac dec 10 1 1e8
meas ac dcgain FIND vdb(VOUTA) AT=1
.endc
.end
