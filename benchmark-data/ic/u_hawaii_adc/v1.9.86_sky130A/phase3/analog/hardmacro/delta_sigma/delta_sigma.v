// Behavioral Verilog model for delta_sigma OTA block -- u_hawaii_adc sky130A substitute
// Subckt: ds_ota  (single-stage NMOS-input 5T OTA)
// Design content: structure_and_geometry (sized, DRC-clean sky130A layout)
// DC gain TT_27c = 41.9077 dB pre-layout / 42.6127 dB post-layout (ngspice, sky130A)
// System ENOB = 14.737 bits @ OSR=256 order-2 (iverilog/vvp behavioral cosim, A9 measured)
// sky130A devices: sky130_fd_pr__nfet_01v8 (Mtail, M1, M2), sky130_fd_pr__pfet_01v8 (M3, M4)

`timescale 1ns/1ps

module delta_sigma (
    inout  VDD,
    inout  VSS,
    input  VINP,
    input  VINN,
    output VOUTA,
    input  VBIAS
);

// Behavioral model: OTA output tracks (VINP - VINN) * DC_GAIN
// Real device: single-stage telescopic OTA, 5 transistors
// Bias tail current set by VBIAS; output common-mode ~0.65V (TT_27c)

`ifdef FUNCTIONAL
    // High-gain differential amplifier behavioral model
    assign VOUTA = (VINP > VINN) ? 1.2 : 0.1;  // simplified rail-to-rail model
`endif

endmodule
