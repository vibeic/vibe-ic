// Auto-generated SoC integration wrapper (APB-lite).
// Wraps tilelink and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: tilelink
// Register file present (L4): no

`timescale 1ns/1ps

module tilelink_soc_wrap (
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
    input  A,  // Carries request messages sent to a particular address.
    input  B,  // Carries request messages sent to a cached data block held by a master.
    input  C,  // Carries response messages to channel-B requests and voluntary write-backs.
    input  D,  // Carries response messages for channel-A requests, ReleaseAck for channel-C voluntary writebacks, and Grant/GrantData for Acquires.
    input  E  // Carries acknowledgements of channel-D Grant/GrantData (GrantAck), used for operation serialization.
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
    tilelink u_tilelink (
        .A(A),
        .B(B),
        .C(C),
        .D(D),
        .E(E),
        .clock(PCLK),
        .reset(PRESETn)
    );

endmodule
