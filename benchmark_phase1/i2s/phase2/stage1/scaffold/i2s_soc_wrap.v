// Auto-generated SoC integration wrapper (APB-lite).
// Wraps i2s and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: i2s
// Register file present (L4): no

`timescale 1ns/1ps

module i2s_soc_wrap (
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
    inout  SCK,  // Continuous Serial Clock; one rising edge per data bit.
    inout  WS,  // Word Select; 0 = channel 1 (left), 1 = channel 2 (right). Changes one SCK period BEFORE the MSB of the next word.
    inout  SD  // Serial Data; MSB-first two's-complement audio samples for both channels time-multiplexed.
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
    i2s u_i2s (
        .SCK(SCK),
        .WS(WS),
        .SD(SD),
        .clk(PCLK),
        .rst_n(PRESETn)
    );

endmodule
