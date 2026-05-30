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
    reg [7:0] MEMMAP_LOW_009E8B00; // offset 0x9E8B00 (ro)
    reg [7:0] MEMMAP_HIGH_009E8B3F; // offset 0x9E8B3F (ro)
    reg [7:0] MEMMAP_LOW_00000040; // offset 0x0040 (ro)
    reg [7:0] MEMMAP_HIGH_0000FFFF; // offset 0xFFFF (ro)
    reg [7:0] MEMMAP_LOW_00000020; // offset 0x0020 (ro)
    reg [7:0] MEMMAP_HIGH_0000003E; // offset 0x003E (ro)
    reg [7:0] MEMMAP_HIGH_0000007F; // offset 0x007F (ro)
    reg [7:0] MEMMAP_LOW_00000001; // offset 0x0001 (ro)
    reg [7:0] MEMMAP_HIGH_00000EFF; // offset 0x0EFF (ro)
    reg [7:0] MEMMAP_LOW_00000100; // offset 0x0100 (ro)
    reg [7:0] MEMMAP_HIGH_000001FF; // offset 0x01FF (ro)
    reg [7:0] MEMMAP_LOW_00000300; // offset 0x0300 (ro)
    reg [7:0] MEMMAP_HIGH_000003FF; // offset 0x03FF (ro)
    reg [7:0] MEMMAP_LOW_00000500; // offset 0x0500 (ro)
    reg [7:0] MEMMAP_HIGH_000005FF; // offset 0x05FF (ro)
    reg [7:0] MEMMAP_LOW_00000700; // offset 0x0700 (ro)
    reg [7:0] MEMMAP_HIGH_000007FF; // offset 0x07FF (ro)
    reg [7:0] MEMMAP_LOW_00000900; // offset 0x0900 (ro)
    reg [7:0] MEMMAP_HIGH_000009FF; // offset 0x09FF (ro)
    reg [7:0] MEMMAP_LOW_00000B00; // offset 0x0B00 (ro)
    reg [7:0] MEMMAP_HIGH_00000BFF; // offset 0x0BFF (ro)
    reg [7:0] MEMMAP_HIGH_00003FFF; // offset 0x3FFF (ro)
    reg [7:0] MEMMAP_LOW_00000000; // offset 0x0000 (ro)
    reg [7:0] MEMMAP_LOW_00000007; // offset 0x0007 (ro)
    reg [7:0] MEMMAP_LOW_00000002; // offset 0x0002 (ro)
    reg [7:0] MEMMAP_HIGH_000F423F; // offset 0x000F423F (ro)
    reg [7:0] MEMMAP_HIGH_000000FF; // offset 0xFF (ro)
    reg [7:0] MEMMAP_LOW_00000080; // offset 0x80 (ro)
    reg [7:0] MEMMAP_HIGH_0000009F; // offset 0x9F (ro)
    reg [7:0] MEMMAP_LOW_000000E0; // offset 0xE0 (ro)
    reg [7:0] MEMMAP_LOW_00000005; // offset 0x05 (ro)
    reg [7:0] MEMMAP_LOW_0000000D; // offset 0x0D (ro)
    reg [7:0] MEMMAP_HIGH_0000000F; // offset 0x0F (ro)
    reg [7:0] MEMMAP_HIGH_FFFFFFFE; // offset 0xFFFFFFFE (ro)
    reg [7:0] MEMMAP_LOW_00000025; // offset 0x25 (ro)
    reg [7:0] MEMMAP_HIGH_00000027; // offset 0x27 (ro)
    reg [7:0] MEMMAP_HIGH_000000EF; // offset 0xEF (ro)
    reg [7:0] MEMMAP_HIGH_00000003; // offset 0x03 (ro)
    reg [7:0] MEMMAP_LOW_00000004; // offset 0x04 (ro)
    reg [7:0] MEMMAP_LOW_00000008; // offset 0x08 (ro)
    reg [7:0] MEMMAP_HIGH_0000000B; // offset 0x0B (ro)
    reg [7:0] MEMMAP_LOW_0000000C; // offset 0x0C (ro)
    reg [7:0] MEMMAP_LOW_00000010; // offset 0x10 (ro)
    reg [7:0] MEMMAP_HIGH_00000013; // offset 0x13 (ro)
    reg [7:0] MEMMAP_HIGH_0000004B; // offset 0x4B (ro)
    reg [7:0] MEMMAP_HIGH_0000003F; // offset 0x3F (ro)
    reg [7:0] MEMMAP_LOW_00000028; // offset 0x28 (ro)
    reg [7:0] MEMMAP_LOW_000000A4; // offset 0x00A4 (ro)
    reg [7:0] MEMMAP_HIGH_00002148; // offset 0x2148 (ro)
    reg [7:0] MEMMAP_LOW_0000001B; // offset 0x001B (ro)
    reg [7:0] MEMMAP_HIGH_00000014; // offset 0x14 (ro)

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            MEMMAP_LOW_009E8B00 <= 8'b0;
            MEMMAP_HIGH_009E8B3F <= 8'b0;
            MEMMAP_LOW_00000040 <= 8'b0;
            MEMMAP_HIGH_0000FFFF <= 8'b0;
            MEMMAP_LOW_00000020 <= 8'b0;
            MEMMAP_HIGH_0000003E <= 8'b0;
            MEMMAP_HIGH_0000007F <= 8'b0;
            MEMMAP_LOW_00000001 <= 8'b0;
            MEMMAP_HIGH_00000EFF <= 8'b0;
            MEMMAP_LOW_00000100 <= 8'b0;
            MEMMAP_HIGH_000001FF <= 8'b0;
            MEMMAP_LOW_00000300 <= 8'b0;
            MEMMAP_HIGH_000003FF <= 8'b0;
            MEMMAP_LOW_00000500 <= 8'b0;
            MEMMAP_HIGH_000005FF <= 8'b0;
            MEMMAP_LOW_00000700 <= 8'b0;
            MEMMAP_HIGH_000007FF <= 8'b0;
            MEMMAP_LOW_00000900 <= 8'b0;
            MEMMAP_HIGH_000009FF <= 8'b0;
            MEMMAP_LOW_00000B00 <= 8'b0;
            MEMMAP_HIGH_00000BFF <= 8'b0;
            MEMMAP_HIGH_00003FFF <= 8'b0;
            MEMMAP_LOW_00000000 <= 8'b0;
            MEMMAP_LOW_00000007 <= 8'b0;
            MEMMAP_LOW_00000002 <= 8'b0;
            MEMMAP_HIGH_000F423F <= 8'b0;
            MEMMAP_HIGH_000000FF <= 8'b0;
            MEMMAP_LOW_00000080 <= 8'b0;
            MEMMAP_HIGH_0000009F <= 8'b0;
            MEMMAP_LOW_000000E0 <= 8'b0;
            MEMMAP_LOW_00000005 <= 8'b0;
            MEMMAP_LOW_0000000D <= 8'b0;
            MEMMAP_HIGH_0000000F <= 8'b0;
            MEMMAP_HIGH_FFFFFFFE <= 8'b0;
            MEMMAP_LOW_00000025 <= 8'b0;
            MEMMAP_HIGH_00000027 <= 8'b0;
            MEMMAP_HIGH_000000EF <= 8'b0;
            MEMMAP_HIGH_00000003 <= 8'b0;
            MEMMAP_LOW_00000004 <= 8'b0;
            MEMMAP_LOW_00000008 <= 8'b0;
            MEMMAP_HIGH_0000000B <= 8'b0;
            MEMMAP_LOW_0000000C <= 8'b0;
            MEMMAP_LOW_00000010 <= 8'b0;
            MEMMAP_HIGH_00000013 <= 8'b0;
            MEMMAP_HIGH_0000004B <= 8'b0;
            MEMMAP_HIGH_0000003F <= 8'b0;
            MEMMAP_LOW_00000028 <= 8'b0;
            MEMMAP_LOW_000000A4 <= 8'b0;
            MEMMAP_HIGH_00002148 <= 8'b0;
            MEMMAP_LOW_0000001B <= 8'b0;
            MEMMAP_HIGH_00000014 <= 8'b0;
        end else if (reg_we) begin
            // TODO — address decode (per L4 offsets)
        end
    end

    // Read mux (TODO — match the offsets above)
    always @(*) begin
        reg_rdata = 32'b0;
    end

endmodule
