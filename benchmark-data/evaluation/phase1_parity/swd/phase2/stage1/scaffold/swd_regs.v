// Auto-generated register-file skeleton.
// Address decode + read/write hooks are stubbed; behavior is TODO.
// Top module: swd

`timescale 1ns/1ps

module swd_regs (
    input         clk,
    input         rst_n,
    input  [31:0] reg_addr,
    input         reg_we,
    input  [31:0] reg_wdata,
    output reg [31:0] reg_rdata
);

    // Register declarations
    reg [7:0] MEMMAP_LOW_00000024; // offset 0x24 (ro)
    reg [7:0] MEMMAP_HIGH_000000EC; // offset 0xEC (ro)
    reg [7:0] MEMMAP_LOW_00000020; // offset 0x20 (ro)
    reg [7:0] MEMMAP_HIGH_000000F8; // offset 0xF8 (ro)
    reg [7:0] MEMMAP_LOW_00000002; // offset 0x2 (ro)
    reg [7:0] MEMMAP_HIGH_00000008; // offset 0x8 (ro)

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            MEMMAP_LOW_00000024 <= 8'b0;
            MEMMAP_HIGH_000000EC <= 8'b0;
            MEMMAP_LOW_00000020 <= 8'b0;
            MEMMAP_HIGH_000000F8 <= 8'b0;
            MEMMAP_LOW_00000002 <= 8'b0;
            MEMMAP_HIGH_00000008 <= 8'b0;
        end else if (reg_we) begin
            // TODO — address decode (per L4 offsets)
        end
    end

    // Read mux (TODO — match the offsets above)
    always @(*) begin
        reg_rdata = 32'b0;
    end

endmodule
