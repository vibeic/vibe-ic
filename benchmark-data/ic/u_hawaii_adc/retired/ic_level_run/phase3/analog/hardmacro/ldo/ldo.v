// u_hawaii_adc LDO -- behavioral Verilog wrapper for mixed-signal integration.
// GENERATED from L5 Block B spec. Analog block (real_value behaviour); the
// SPICE schematic (ldo.sp) + 9-corner ngspice sweep is the sign-off model.
// SG13G2 LEVEL=1 standin -> MODELED, not silicon sign-off.
`timescale 1ns/1ps
module ldo (
    inout  IOVDD,   // 1.8 V supply in
    inout  VSS,
    input  VREF,    // 0.6 V reference
    output VOUT     // regulated 1.2 V CORE out
);
    // behavioral: VOUT regulates to 1.2 V (real-number modelling done in cosim)
    // tie-off for digital integration LEC; analog behaviour lives in SPICE.
    assign VOUT = 1'bz;   // analog node -- driven by the SPICE/real model
endmodule
