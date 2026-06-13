// Auto-generated SoC integration wrapper (APB-lite).
// Wraps HBM3_stack_on_interposer and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: HBM3_stack_on_interposer
// Register file present (L4): no

`timescale 1ns/1ps

module HBM3_stack_on_interposer_soc_wrap (
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
    inout  CK_t_CK_c,  // Per-channel differential clock; commands registered at rising edges; channels need not be synchronous.
    inout  R_row_command_address,  // ACTIVATE/PRECHARGE/REFRESH/RFM/MRS with bank-group/bank/row. Per channel.
    inout  C_column_command_address,  // READ/WRITE with column; decoded independently per 32-bit pseudo-channel.
    inout  DQ,  // 64-bit-per-channel data bus (1024 bits/stack); 32 bits/pseudo-channel; double data rate.
    input  WDQS_t_WDQS_c,  // Differential write strobe, per pseudo-channel; both edges sampled.
    input  RDQS_t_RDQS_c,  // Differential read strobe, per pseudo-channel; both edges sampled.
    input  DM_DBI,  // Data mask / data-bus-inversion.
    inout  ECC_parity_bits,  // Link-ECC and DQ-parity protecting data and command/address.
    input  AERR_DERR,  // RAS alert / error report (CA parity, ECC uncorrectable, severity).
    input  TEMP  // Temperature readout for refresh adaptation.
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
    HBM3_stack_on_interposer u_HBM3_stack_on_interposer (
        .CK_t_CK_c(CK_t_CK_c),
        .R_row_command_address(R_row_command_address),
        .C_column_command_address(C_column_command_address),
        .DQ(DQ),
        .WDQS_t_WDQS_c(WDQS_t_WDQS_c),
        .RDQS_t_RDQS_c(RDQS_t_RDQS_c),
        .DM_DBI(DM_DBI),
        .ECC_parity_bits(ECC_parity_bits),
        .AERR_DERR(AERR_DERR),
        .TEMP(TEMP),
        .RESET_n(PRESETn),
        .clk(PCLK)
    );

endmodule
