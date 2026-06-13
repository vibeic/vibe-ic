// Auto-generated SoC integration wrapper (APB-lite).
// Wraps ONFI_NAND_Target and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: ONFI_NAND_Target
// Register file present (L4): yes

`timescale 1ns/1ps

module ONFI_NAND_Target_soc_wrap (
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
    inout  CE_n,  // Chip Enable (active-low); selects target.
    inout  CLE,  // Command Latch Enable.
    inout  ALE,  // Address Latch Enable.
    inout  WE_n_CLK,  // Write Enable (SDR) / Clock (NV-DDR); shared pin.
    inout  RE_n_RE_t_W_R_n,  // Read Enable / NV-DDR3 differential / NV-DDR direction; shared pin.
    inout  RE_c,  // Read Enable Complement (NV-DDR2/3 optional).
    inout  WP_n,  // Write Protect; disables Program/Erase when LOW.
    inout  R_B_n,  // Ready/Busy; LOW = busy.
    inout  [7:0] DQ,  // 8-bit data bus (cmd/addr/data).
    inout  DQ_15_8,  // Upper 8 bits (SDR x16).
    inout  DQS_DQS_t,  // Data Strobe True (NV-DDR family).
    inout  DQS_c,  // Data Strobe Complement (NV-DDR2/3 optional).
    inout  VREFQ,  // Input reference voltage (NV-DDR2/3).
    inout  ZQ,  // ZQ Calibration reference; tied to Vss via RZQ.
    inout  ENi,  // Enumeration input (CE_n pin reduction).
    inout  ENo  // Enumeration output (CE_n pin reduction).
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // APB -> register-file decode stub.
    // The protocol exposes 1 register(s) (from L4).
    // TODO: connect PWDATA/PRDATA to the block's register file
    //       using the offsets below, then instantiate the block.
    // -----------------------------------------------------------
    // offset          PAGE [8b, rw]

    always @(*) begin
        PRDATA = 32'h0;
        if (apb_read) begin
            case (PADDR)
                // TODO: 12'hXXX: PRDATA = <reg>;  per offsets above
                default: PRDATA = 32'h0;
            endcase
        end
    end

    // TODO: on apb_write, decode PADDR and update the block's
    //       register file (writes are stubbed out for now).

    // Wrapped protocol-block instance.
    ONFI_NAND_Target u_ONFI_NAND_Target (
        .CE_n(CE_n),
        .CLE(CLE),
        .ALE(ALE),
        .WE_n_CLK(WE_n_CLK),
        .RE_n_RE_t_W_R_n(RE_n_RE_t_W_R_n),
        .RE_c(RE_c),
        .WP_n(WP_n),
        .R_B_n(R_B_n),
        .DQ(DQ),
        .DQ_15_8(DQ_15_8),
        .DQS_DQS_t(DQS_DQS_t),
        .DQS_c(DQS_c),
        .VREFQ(VREFQ),
        .ZQ(ZQ),
        .ENi(ENi),
        .ENo(ENo),
        .rst_n(PRESETn)
    );

endmodule
