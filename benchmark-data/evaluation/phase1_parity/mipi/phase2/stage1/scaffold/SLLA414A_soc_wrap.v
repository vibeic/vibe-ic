// Auto-generated SoC integration wrapper (APB-lite).
// Wraps SLLA414A and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: SLLA414A
// Register file present (L4): no

`timescale 1ns/1ps

module SLLA414A_soc_wrap (
    // ---- APB-lite register-access bus ----
    input         PCLK,
    input         PRESETn,
    input  [11:0] PADDR,
    input         PSEL,
    input         PENABLE,
    input         PWRITE,
    input  [31:0] PWDATA,
    output reg [31:0] PRDATA,
    output        PREADY
    ,
    // ---- native protocol ports (passthrough to pads) ----
    inout  CLK_P,  // Differential Clock Lane positive; DDR — both edges latch one Data-Lane bit.
    inout  CLK_N,  // Differential Clock Lane negative.
    inout  DAT0_P,  // Differential Data Lane 0 positive; carries CSI-2 packet bytes during HS.
    inout  DAT0_N,  // Differential Data Lane 0 negative.
    inout  DAT1_P_DAT1_N_optional,  // Data Lane 1 — present when N_data_lanes ≥ 2.
    inout  DAT2_P_DAT2_N_optional,  // Data Lane 2 — present when N_data_lanes ≥ 3.
    inout  DAT3_P_DAT3_N_optional  // Data Lane 3 — present when N_data_lanes = 4.
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // No register file (L4 empty). Expose a read-only ID register
    // so the SoC can still probe the wrapper, and pass the block's
    // native ports through to the wrapper boundary.
    // -----------------------------------------------------------
    localparam [31:0] WRAP_ID = 32'h5343_5750; // "SCWP"

    always @(*) begin
        PRDATA = 32'h0;
        if (apb_read) begin
            case (PADDR)
                12'h000: PRDATA = WRAP_ID; // read-only ID register
                default: PRDATA = 32'h0;
            endcase
        end
    end

    // Wrapped protocol-block instance.
    SLLA414A u_SLLA414A (
        .CLK_P(CLK_P),
        .CLK_N(CLK_N),
        .DAT0_P(DAT0_P),
        .DAT0_N(DAT0_N),
        .DAT1_P_DAT1_N_optional(DAT1_P_DAT1_N_optional),
        .DAT2_P_DAT2_N_optional(DAT2_P_DAT2_N_optional),
        .DAT3_P_DAT3_N_optional(DAT3_P_DAT3_N_optional),
        .rst_n(PRESETn)
    );

endmodule
