// Auto-generated SoC integration wrapper (APB-lite).
// Wraps PM_PME and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: PM_PME
// Register file present (L4): no

`timescale 1ns/1ps

module PM_PME_soc_wrap (
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
    output TXp,  // Positive line of the differential transmit pair.
    output TXn,  // Negative line of the differential transmit pair.
    input  RXp,  // Positive line of the differential receive pair.
    input  RXn,  // Negative line of the differential receive pair.
    input  WAKE  // Pulled LOW by any device that wants to resume from L2 / L3.
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
    PM_PME u_PM_PME (
        .TXp(TXp),
        .TXn(TXn),
        .RXp(RXp),
        .RXn(RXn),
        .REFCLK(PCLK),
        .PERST(PRESETn),
        .WAKE(WAKE)
    );

endmodule
