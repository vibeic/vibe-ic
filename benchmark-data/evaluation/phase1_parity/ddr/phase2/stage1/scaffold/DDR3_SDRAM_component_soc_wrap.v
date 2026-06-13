// Auto-generated SoC integration wrapper (APB-lite).
// Wraps DDR3_SDRAM_component and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: DDR3_SDRAM_component
// Register file present (L4): yes

`timescale 1ns/1ps

module DDR3_SDRAM_component_soc_wrap (
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
    inout  CK,  // Differential clock input (positive half).
    inout  CKE,  // Clock Enable.
    inout  CS,  // Chip Select.
    inout  RAS_CAS_WE,  // Command inputs.
    inout  [2:0] BA,  // Bank Address.
    inout  [15:0] A,  // Multiplexed address.
    inout  DM,  // Write Data Mask.
    inout  ODT,  // On-Die Termination control.
    inout  RESET,  // Active-low asynchronous reset.
    inout  DQ,  // Data bus.
    inout  DQS_DQS,  // Bidirectional differential data strobe.
    inout  TDQS_TDQS,  // Termination Data Strobe.
    input  ZQ,  // Calibration reference (240 Ω external).
    input  VREFDQ,  // DQ input threshold reference (VDDQ/2).
    input  VREFCA  // CA input threshold reference (VDD/2).
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
    // offset          MODE [8b, rw]

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
    DDR3_SDRAM_component u_DDR3_SDRAM_component (
        .CK(CK),
        .CKE(CKE),
        .CS(CS),
        .RAS_CAS_WE(RAS_CAS_WE),
        .BA(BA),
        .A(A),
        .DM(DM),
        .ODT(ODT),
        .RESET(RESET),
        .DQ(DQ),
        .DQS_DQS(DQS_DQS),
        .TDQS_TDQS(TDQS_TDQS),
        .ZQ(ZQ),
        .VREFDQ(VREFDQ),
        .VREFCA(VREFCA),
        .clk(PCLK)
    );

endmodule
