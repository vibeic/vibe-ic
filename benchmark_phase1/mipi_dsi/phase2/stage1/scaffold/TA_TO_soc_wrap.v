// Auto-generated SoC integration wrapper (APB-lite).
// Wraps TA_TO and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: TA_TO
// Register file present (L4): no

`timescale 1ns/1ps

module TA_TO_soc_wrap (
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
    inout  Clock,  // Differential Clock Lane positive; DDR.
    inout  Data0,  // Differential Data Lane 0 positive; bidirectional in LP.
    inout  Data1_Data1_optional,  // Data Lane 1 — unidirectional.
    inout  Data2_Data2_optional,  // Data Lane 2 — unidirectional.
    inout  Data3_Data3_optional  // Data Lane 3 — unidirectional.
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
    TA_TO u_TA_TO (
        .Clock(Clock),
        .Data0(Data0),
        .Data1_Data1_optional(Data1_Data1_optional),
        .Data2_Data2_optional(Data2_Data2_optional),
        .Data3_Data3_optional(Data3_Data3_optional),
        .rst_n(PRESETn)
    );

endmodule
