// Auto-generated register-file skeleton.
// Address decode + read/write hooks are stubbed; behavior is TODO.
// Top module: M_CAN

`timescale 1ns/1ps

module M_CAN_regs (
    input         clk,
    input         rst_n,
    input  [31:0] reg_addr,
    input         reg_we,
    input  [31:0] reg_wdata,
    output reg [31:0] reg_rdata
);

    // Register declarations
    reg [7:0] MEMMAP_LOW_00000000; // offset 0x00 (ro)
    reg [7:0] MEMMAP_HIGH_0000001F; // offset 0x1F (ro)
    reg [7:0] MEMMAP_LOW_00000001; // offset 0x1 (ro)
    reg [7:0] MEMMAP_HIGH_0000000F; // offset 0xF (ro)
    reg [7:0] MEMMAP_HIGH_0000007F; // offset 0x7F (ro)
    reg [7:0] MEMMAP_HIGH_000001FF; // offset 0x1FF (ro)
    reg [7:0] MEMMAP_HIGH_000000FF; // offset 0xFF (ro)

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            MEMMAP_LOW_00000000 <= 8'b0;
            MEMMAP_HIGH_0000001F <= 8'b0;
            MEMMAP_LOW_00000001 <= 8'b0;
            MEMMAP_HIGH_0000000F <= 8'b0;
            MEMMAP_HIGH_0000007F <= 8'b0;
            MEMMAP_HIGH_000001FF <= 8'b0;
            MEMMAP_HIGH_000000FF <= 8'b0;
        end else if (reg_we) begin
            // TODO — address decode (per L4 offsets)
        end
    end

    // Read mux (TODO — match the offsets above)
    always @(*) begin
        reg_rdata = 32'b0;
    end

endmodule
