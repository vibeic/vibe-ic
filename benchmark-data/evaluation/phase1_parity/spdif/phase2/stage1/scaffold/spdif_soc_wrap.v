// Auto-generated SoC integration wrapper (APB-lite).
// Wraps spdif and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: spdif
// Register file present (L4): no

`timescale 1ns/1ps

module spdif_soc_wrap (
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
    inout  SPDIF_TX_coax,  // Single-wire 75 Ω coaxial output carrying BMC-encoded IEC 60958 type II stream.
    inout  SPDIF_RX_coax,  // Single-wire 75 Ω coaxial input; the receiver-side counterpart of SPDIF_TX (in transceiver ICs, the same pin or its differential).
    inout  SPDIF_Toslink_Tx,  // Toslink (JIS F05 / EIAJ optical) LED driver carrying BMC-encoded IEC 60958 type II stream.
    inout  SPDIF_Toslink_Rx  // Toslink optical receiver photodiode + comparator; converts optical pulses back to digital BMC stream.
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
    spdif u_spdif (
        .SPDIF_TX_coax(SPDIF_TX_coax),
        .SPDIF_RX_coax(SPDIF_RX_coax),
        .SPDIF_Toslink_Tx(SPDIF_Toslink_Tx),
        .SPDIF_Toslink_Rx(SPDIF_Toslink_Rx),
        .clk(PCLK),
        .rst_n(PRESETn)
    );

endmodule
