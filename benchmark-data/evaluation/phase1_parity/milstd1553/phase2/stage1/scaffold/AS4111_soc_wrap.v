// Auto-generated SoC integration wrapper (APB-lite).
// Wraps AS4111 and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: AS4111
// Register file present (L4): no

`timescale 1ns/1ps

module AS4111_soc_wrap (
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
    input  Bus_A_primary,  // Primary 78 Ω twinax bus carrying Manchester II 1.0 Mbit/s; one BC + up to 31 RTs share it.
    input  Bus_B_redundant  // Standby 78 Ω twinax bus identical to Bus A; used for retry / failover; messages travel on only one of A/B at a time.
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
    AS4111 u_AS4111 (
        .Bus_A_primary(Bus_A_primary),
        .Bus_B_redundant(Bus_B_redundant),
        .clk(PCLK),
        .rst_n(PRESETn)
    );

endmodule
