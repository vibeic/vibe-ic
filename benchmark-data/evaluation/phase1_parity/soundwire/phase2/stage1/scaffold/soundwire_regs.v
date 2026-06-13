// Auto-generated register-file skeleton.
// Address decode + read/write hooks are stubbed; behavior is TODO.
// Top module: soundwire

`timescale 1ns/1ps

module soundwire_regs (
    input         clk,
    input         rst_n,
    input  [31:0] reg_addr,
    input         reg_we,
    input  [31:0] reg_wdata,
    output reg [31:0] reg_rdata
);

    // Register declarations
    reg [7:0] MEMMAP_LOW_00000000; // offset 0x0 (ro)
    reg [7:0] MEMMAP_HIGH_00000FFF; // offset 0xFFF (ro)
    reg [7:0] MEMMAP_LOW_00001000; // offset 0x1000 (ro)
    reg [7:0] MEMMAP_HIGH_000017FF; // offset 0x17FF (ro)
    reg [7:0] MEMMAP_LOW_00002000; // offset 0x2000 (ro)
    reg [7:0] MEMMAP_HIGH_0000FFFF; // offset 0xFFFF (ro)
    reg [7:0] MEMMAP_LOW_00010000; // offset 0x10000 (ro)
    reg [7:0] MEMMAP_HIGH_3FFFFFFF; // offset 0x3FFFFFFF (ro)

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            MEMMAP_LOW_00000000 <= 8'b0;
            MEMMAP_HIGH_00000FFF <= 8'b0;
            MEMMAP_LOW_00001000 <= 8'b0;
            MEMMAP_HIGH_000017FF <= 8'b0;
            MEMMAP_LOW_00002000 <= 8'b0;
            MEMMAP_HIGH_0000FFFF <= 8'b0;
            MEMMAP_LOW_00010000 <= 8'b0;
            MEMMAP_HIGH_3FFFFFFF <= 8'b0;
        end else if (reg_we) begin
            // TODO — address decode (per L4 offsets)
        end
    end

    // Read mux (TODO — match the offsets above)
    always @(*) begin
        reg_rdata = 32'b0;
    end

endmodule
