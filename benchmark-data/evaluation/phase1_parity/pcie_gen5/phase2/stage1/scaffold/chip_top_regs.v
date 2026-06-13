// Auto-generated register-file skeleton.
// Address decode + read/write hooks are stubbed; behavior is TODO.
// Top module: chip_top

`timescale 1ns/1ps

module chip_top_regs (
    input         clk,
    input         rst_n,
    input  [31:0] reg_addr,
    input         reg_we,
    input  [31:0] reg_wdata,
    output reg [31:0] reg_rdata
);

    // Register declarations
    reg [1:0] IR; // offset  (shift-in / shift-out via tdi / tdo in shiftir; parallel-latched to current-instruction on falling edge of tck in updateir.)
    reg Bypass; // offset  (shift-in / shift-out via tdi / tdo in shiftdr (when bypass / clamp / highz is current).)
    reg BSR; // offset  (shift-in / shift-out via tdi / tdo in shiftdr (when sample/preload / extest / intest is current).)
    reg [31:0] IDCODE; // offset  (shift-out via tdo in shiftdr (when idcode / usercode is current). the register is parallel-loaded with the device id in capturedr; shifted contents into tdi are typically ignored.)

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            IR <= 2'b0;
            Bypass <= 1'b0;
            BSR <= 1'b0;
            IDCODE <= 32'b0;
        end else if (reg_we) begin
            // TODO — address decode (per L4 offsets)
        end
    end

    // Read mux (TODO — match the offsets above)
    always @(*) begin
        reg_rdata = 32'b0;
    end

endmodule
