* netlist_provenance: a3_netlist
* netlist_source: phase3/analog/delta_sigma/delta_sigma.sp
* netlist_testbench: phase3/analog/delta_sigma/tb_delta_sigma.sp
* design_traceable: true
* deck_authored_by: A3_netlist_gen (this deck's circuit is the block netlist; only the corner .lib section and .temp are re-stamped here)
* design_content: structure_and_geometry
* design_content_meaning: structure_and_geometry — at least one device parameter was solved against a bound spec value
* netlist_provenance_ref: None
* tb_delta_sigma -- A4 delivered stimulus deck (OTA open-loop gain; sky130A substitute)
* --- inlined delta_sigma.sp (A3 block netlist) ---
* u_hawaii_adc -- delta_sigma modulator CORE (integrator OTA) -- sky130A retarget (real sky130_fd_pr devices, native ngspice)
* NOTE: L19 tapeout target is IHP SG13G2 (no public ngspice models). This deck
*   is the DISCLOSED open-source sky130A substitute exercising the real ngspice
*   path. The SC switches/caps + decimation are discrete-time/digital and are
*   verified by the behavioral mixed-signal cosim (A9), not this DC/AC deck.
* Analog core: single-stage NMOS-input OTA, long-L for DC-gain margin vs OSR=256
*   integrator-leakage floor (gain >= 20*log10(256) = 48.16 dB).
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice ff
.subckt ds_ota VDD VSS VINP VINN VOUTA VBIAS
* NMOS tail current source
XMtail ntail VBIAS VSS VSS sky130_fd_pr__nfet_01v8 W=4 L=1 m=4
* NMOS input diff pair (long L -> high ro -> high DC gain)
XM1 nd1 VINP ntail VSS sky130_fd_pr__nfet_01v8 W=8 L=2 m=4
XM2 VOUTA VINN ntail VSS sky130_fd_pr__nfet_01v8 W=8 L=2 m=4
* PMOS mirror load (diode at nd1), long L
XM3 nd1  nd1 VDD VDD sky130_fd_pr__pfet_01v8 W=8 L=2 m=4
XM4 VOUTA nd1 VDD VDD sky130_fd_pr__pfet_01v8 W=8 L=2 m=4
.ends ds_ota

* --- end delta_sigma.sp ---
Vdd VDD 0 1.2
Vbias VBIAS 0 0.75
Vcm  CM 0 0.6
Vinp VINP CM AC 1
Lfb  VOUTA VINN 1T
Cbig VINN 0 1
Xdut VDD 0 VINP VINN VOUTA VBIAS ds_ota
Cl VOUTA 0 1p
.temp -40
.control
op
print v(VOUTA)
ac dec 10 1 1e8
meas ac dcgain FIND vdb(VOUTA) AT=1
.endc
.end
