// Behavioral Verilog model for ldo block -- u_hawaii_adc sky130A substitute
// Design content: structure_and_geometry (sized against bound spec values)
// Vout = VREF * (R1+R2)/R2 = 0.6V * 2 = 1.2V @ no-load
// LDO block: PMOS series-pass + NMOS-input 5T OTA + resistor feedback divider
// sky130A: sky130_fd_pr__pfet_01v8 (pass), sky130_fd_pr__nfet_01v8 (OTA),
//          sky130_fd_pr__res_high_po_1p41 (divider), sky130_fd_pr__cap_mim_m3_1 (Miller)
// 2026-08-04: VBIAS added -- the ideal in-block bias source was hoisted to a real
//             block port when the netlist was made layout-realizable for A6.

`timescale 1ns/1ps

module ldo (
    inout  IOVDD,
    inout  VSS,
    input  VREF,
    output VOUT,
    input  VBIAS
);

// Behavioral model: output regulated to 1.2V when IOVDD=1.8V, VREF=0.6V, VBIAS=0.8V
// Measured (ngspice, sky130A tt/27C):
//   pre-layout  Vout = 1.20690 V   PSRR@100Hz = -52.4901 dB
//   post-layout Vout = 1.20781 V   PSRR@100Hz = -53.2685 dB  (extracted RC netlist)

`ifdef FUNCTIONAL
    // Functional/timing model - outputs regulated voltage
    assign VOUT = 1.2;  // nominal regulated output
`endif

endmodule
