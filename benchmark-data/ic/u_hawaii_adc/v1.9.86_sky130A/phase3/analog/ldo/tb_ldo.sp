* tb_ldo -- A4 delivered stimulus deck (sky130A native; corner .lib re-stamped by A4)
* 2026-08-04: VBIAS is now a block port (was an ideal source inside the subckt) and
* the 20 pF LOAD capacitor CL now sits with Iload where topology.md puts it.
* Measurement statements are UNCHANGED so the re-run is comparable to the previous one.
.include ldo.sp
Viovdd IOVDD 0 DC 1.8 AC 1
Vref   VREF  0 0.6
Vbias  VBIAS 0 0.8
Cl     VOUT  0 20p
Iload  VOUT  0 0.5m
Xdut IOVDD 0 VREF VOUT VBIAS ldo
.control
dc Viovdd 1.6 2.0 0.05
meas dc vout FIND v(VOUT) AT=1.8
meas dc dropout PARAM='1.8-vout'
ac dec 10 1 1e6
meas ac psrr FIND vdb(VOUT) AT=100
.endc
.end
