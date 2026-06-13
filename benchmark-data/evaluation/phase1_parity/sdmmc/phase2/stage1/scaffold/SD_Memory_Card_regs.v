// Auto-generated register-file skeleton.
// Address decode + read/write hooks are stubbed; behavior is TODO.
// Top module: SD_Memory_Card

`timescale 1ns/1ps

module SD_Memory_Card_regs (
    input         clk,
    input         rst_n,
    input  [31:0] reg_addr,
    input         reg_we,
    input  [31:0] reg_wdata,
    output reg [31:0] reg_rdata
);

    // Register declarations
    reg [31:0] OCR; // offset  (read (via acmd41 r3 / cmd58 in spi))
    reg [127:0] CID; // offset  (read (cmd2 in sd, cmd10 later))
    reg [127:0] CSD; // offset  (read (cmd9), partial write (cmd27 program_csd))
    reg [15:0] RCA; // offset  (read/published (cmd3 r6))
    reg [15:0] DSR; // offset  (write (cmd4; optional))
    reg [63:0] SCR; // offset  (read (acmd51))
    reg [511:0] SSR; // offset  (read (acmd13))
    reg [31:0] CSR; // offset  (read (every r1 response))

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            OCR <= 32'b0;
            CID <= 128'b0;
            CSD <= 128'b0;
            RCA <= 16'b0;
            DSR <= 16'b0;
            SCR <= 64'b0;
            SSR <= 512'b0;
            CSR <= 32'b0;
        end else if (reg_we) begin
            // TODO — address decode (per L4 offsets)
        end
    end

    // Read mux (TODO — match the offsets above)
    always @(*) begin
        reg_rdata = 32'b0;
    end

endmodule
