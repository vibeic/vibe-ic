// Auto-generated register-file skeleton.
// Address decode + read/write hooks are stubbed; behavior is TODO.
// Top module: PC16550D

`timescale 1ns/1ps

module PC16550D_regs (
    input         clk,
    input         rst_n,
    input  [31:0] reg_addr,
    input         reg_we,
    input  [31:0] reg_wdata,
    output reg [31:0] reg_rdata
);

    // Register declarations
    reg [7:0] RBR; // offset A2:A1:A0 = 000 (read)
    reg [7:0] THR; // offset A2:A1:A0 = 000 (write)
    reg [7:0] IER; // offset A2:A1:A0 = 001 (read / write)
    reg [7:0] IIR; // offset A2:A1:A0 = 010 (read)
    reg [7:0] FCR; // offset A2:A1:A0 = 010 (write)
    reg [7:0] LCR; // offset A2:A1:A0 = 011 (read / write)
    reg [7:0] MCR; // offset A2:A1:A0 = 100 (read / write)
    reg [7:0] LSR; // offset A2:A1:A0 = 101 (read)
    reg [7:0] MSR; // offset A2:A1:A0 = 110 (read)
    reg [7:0] SCR; // offset A2:A1:A0 = 111 (read / write)
    reg [7:0] DLL; // offset A2:A1:A0 = 000 with DLAB=1 (read / write)
    reg [7:0] DLM; // offset A2:A1:A0 = 001 with DLAB=1 (read / write)

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            RBR <= 8'b0;
            THR <= 8'b0;
            IER <= 8'b0;
            IIR <= 8'b0;
            FCR <= 8'b0;
            LCR <= 8'b0;
            MCR <= 8'b0;
            LSR <= 8'b0;
            MSR <= 8'b0;
            SCR <= 8'b0;
            DLL <= 8'b0;
            DLM <= 8'b0;
        end else if (reg_we) begin
            // TODO — address decode (per L4 offsets)
        end
    end

    // Read mux (TODO — match the offsets above)
    always @(*) begin
        reg_rdata = 32'b0;
    end

endmodule
