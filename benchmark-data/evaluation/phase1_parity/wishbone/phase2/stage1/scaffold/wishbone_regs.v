// Auto-generated register-file skeleton.
// Address decode + read/write hooks are stubbed; behavior is TODO.
// Top module: wishbone

`timescale 1ns/1ps

module wishbone_regs (
    input         clk,
    input         rst_n,
    input  [31:0] reg_addr,
    input         reg_we,
    input  [31:0] reg_wdata,
    output reg [31:0] reg_rdata
);

    // Register declarations
    reg [7:0] MEMMAP_LOW_00000000; // offset 0x00 (ro)
    reg [7:0] MEMMAP_HIGH_00000007; // offset 0x07 (ro)
    reg [7:0] MEMMAP_LOW_00000008; // offset 0x08 (ro)
    reg [7:0] MEMMAP_HIGH_0000000F; // offset 0x0F (ro)
    reg [7:0] MEMMAP_LOW_00000010; // offset 0x10 (ro)
    reg [7:0] MEMMAP_HIGH_00000017; // offset 0x17 (ro)
    reg [7:0] MEMMAP_LOW_00000018; // offset 0x18 (ro)
    reg [7:0] MEMMAP_HIGH_0000001F; // offset 0x1F (ro)

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            MEMMAP_LOW_00000000 <= 8'b0;
            MEMMAP_HIGH_00000007 <= 8'b0;
            MEMMAP_LOW_00000008 <= 8'b0;
            MEMMAP_HIGH_0000000F <= 8'b0;
            MEMMAP_LOW_00000010 <= 8'b0;
            MEMMAP_HIGH_00000017 <= 8'b0;
            MEMMAP_LOW_00000018 <= 8'b0;
            MEMMAP_HIGH_0000001F <= 8'b0;
        end else if (reg_we) begin
            // TODO — address decode (per L4 offsets)
        end
    end

    // Read mux (TODO — match the offsets above)
    always @(*) begin
        reg_rdata = 32'b0;
    end

endmodule
