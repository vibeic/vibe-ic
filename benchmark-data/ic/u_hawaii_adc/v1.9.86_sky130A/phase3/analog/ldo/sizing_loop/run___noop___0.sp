* netlist_provenance: a3_netlist
* netlist_source: phase3/analog/ldo/ldo.sp
* netlist_testbench: phase3/analog/ldo/tb_ldo.sp
* design_traceable: true
* deck_authored_by: A3_netlist_gen (this deck's circuit is the block netlist; only the corner .lib section and .temp are re-stamped here)
* design_content: structure_and_geometry
* design_content_meaning: structure_and_geometry — at least one device parameter was solved against a bound spec value
* netlist_provenance_ref: None
* tb_ldo -- A4 delivered stimulus deck (sky130A native; corner .lib re-stamped by A4)
* 2026-08-04: VBIAS is now a block port (was an ideal source inside the subckt) and
* the 20 pF LOAD capacitor CL now sits with Iload where topology.md puts it.
* Measurement statements are UNCHANGED so the re-run is comparable to the previous one.
* --- inlined ldo.sp (A3 block netlist) ---
* u_hawaii_adc -- LDO block -- sky130A retarget (real sky130_fd_pr devices, native ngspice)
*   datasheet tapeout PDK is IHP SG13G2; this benchmark run (sky130A identity)
*   retargets this block to sky130A. sky130_fd_pr__{n,p}fet_01v8 are real 1.8V devices;
*   wide devices use the m= parallel multiplier to stay in-bin.
* Topology (designer choice R3): PMOS series-pass + NMOS-input 5T OTA
*   + resistor feedback divider + Miller compensation.
*
* A3 REVISION (2026-08-04, physical-realizability):
*   The previous revision of this deck was NOT layout-realizable and therefore
*   could never close A6 (per-block LVS).  Three non-physical elements were
*   replaced with PDK primitives / block ports.  Topology, device geometry and
*   the divider ratio are UNCHANGED.
*     1. `Vbias nbias VSS 0.8` -- an ideal voltage source INSIDE the block.
*        Hoisted to block port VBIAS (the testbench drives the same 0.8 V);
*        electrically identical, and the block now has a real bias pin.
*     2. `R1/R2 = 100k` ideal resistors -> sky130_fd_pr__res_high_po_1p41
*        L=440.9 um (rho=319.8 ohm/sq, W=1.41 um -> 99.9998 kohm each).
*        W=1.41 (not 0.69) because the 0p69 gencell violates sky130 rpm.1
*        (RPM/URPM width >= 1.27 um) and cannot be drawn DRC-clean.
*     3. `Cc = 3p` ideal cap -> 2 x sky130_fd_pr__cap_mim_m3_1 27.5x27.5 um
*        (1.533 pF each -> 3.066 pF).  A single MIM is capped at 30x30 um.
*     4. `Cl = 20p` is the LOAD capacitor (topology.md: "Vout(1.2) -- CL, Iload")
*        and belongs to the load, not the block.  Moved into tb_ldo.sp next to
*        Iload.  The block sees the identical node loading.
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt
.subckt ldo IOVDD VSS VREF VOUT VBIAS
XMtail ntail VBIAS VSS VSS sky130_fd_pr__nfet_01v8 W=4 L=1 m=4
XM1 nd1 FB   ntail VSS sky130_fd_pr__nfet_01v8 W=5 L=0.5 m=4
XM2 nd2 VREF ntail VSS sky130_fd_pr__nfet_01v8 W=5 L=0.5 m=4
XM3 nd1 nd1 IOVDD IOVDD sky130_fd_pr__pfet_01v8 W=5 L=0.5 m=4
XM4 nd2 nd1 IOVDD IOVDD sky130_fd_pr__pfet_01v8 W=5 L=0.5 m=4
XMp VOUT nd2 IOVDD IOVDD sky130_fd_pr__pfet_01v8 W=6 L=0.15 m=120
XCc1 nd2 VOUT sky130_fd_pr__cap_mim_m3_1 W=27.5 L=27.5
XCc2 nd2 VOUT sky130_fd_pr__cap_mim_m3_1 W=27.5 L=27.5
XR1 VOUT FB  VSS sky130_fd_pr__res_high_po_1p41 L=440.9
XR2 FB   VSS VSS sky130_fd_pr__res_high_po_1p41 L=440.9
.ends ldo

* --- end ldo.sp ---
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
