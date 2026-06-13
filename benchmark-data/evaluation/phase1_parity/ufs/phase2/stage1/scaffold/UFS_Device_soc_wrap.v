// Auto-generated SoC integration wrapper (APB-lite).
// Wraps UFS_Device and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: UFS_Device
// Register file present (L4): no

`timescale 1ns/1ps

module UFS_Device_soc_wrap (
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
    inout  REF_CLK,  // Reference clock supplied by the host; seeds the device PLL. Frequency selected via bRefClkFreq (e.g. 19.2 / 26 / 38.4 / 52 MHz).
    inout  RESET_n,  // Active-low device reset.
    input  DOUT0_t_DOUT0_c,  // M-PHY TX lane 0 differential pair (device transmit).
    input  DIN0_t_DIN0_c,  // M-PHY RX lane 0 differential pair (device receive).
    input  DOUT1_t_DOUT1_c,  // M-PHY TX lane 1 differential pair (optional second lane).
    input  DIN1_t_DIN1_c  // M-PHY RX lane 1 differential pair (optional second lane).
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
    UFS_Device u_UFS_Device (
        .REF_CLK(REF_CLK),
        .RESET_n(RESET_n),
        .DOUT0_t_DOUT0_c(DOUT0_t_DOUT0_c),
        .DIN0_t_DIN0_c(DIN0_t_DIN0_c),
        .DOUT1_t_DOUT1_c(DOUT1_t_DOUT1_c),
        .DIN1_t_DIN1_c(DIN1_t_DIN1_c)
    );

endmodule
