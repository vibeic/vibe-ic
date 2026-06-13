// Auto-generated SoC integration wrapper (APB-lite).
// Wraps PC16550D and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: PC16550D
// Register file present (L4): yes

`timescale 1ns/1ps

module PC16550D_soc_wrap (
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
    input  VDD,  // +5 V ± 10 % supply.
    input  VSS  // Ground (0 V).
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // APB -> register-file decode stub.
    // The protocol exposes 12 register(s) (from L4).
    // TODO: connect PWDATA/PRDATA to the block's register file
    //       using the offsets below, then instantiate the block.
    // -----------------------------------------------------------
    // offset A2:A1:A0 = 000 RBR [8b, read]
    // offset A2:A1:A0 = 000 THR [8b, write]
    // offset A2:A1:A0 = 001 IER [8b, read / write]
    // offset A2:A1:A0 = 010 IIR [8b, read]
    // offset A2:A1:A0 = 010 FCR [8b, write]
    // offset A2:A1:A0 = 011 LCR [8b, read / write]
    // offset A2:A1:A0 = 100 MCR [8b, read / write]
    // offset A2:A1:A0 = 101 LSR [8b, read]
    // offset A2:A1:A0 = 110 MSR [8b, read]
    // offset A2:A1:A0 = 111 SCR [8b, read / write]
    // offset A2:A1:A0 = 000 with DLAB=1 DLL [8b, read / write]
    // offset A2:A1:A0 = 001 with DLAB=1 DLM [8b, read / write]

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
    PC16550D u_PC16550D (
        .VDD(VDD),
        .VSS(VSS),
        .clk(PCLK),
        .rst_n(PRESETn)
    );

endmodule
