// Auto-generated register-file skeleton.
// Address decode + read/write hooks are stubbed; behavior is TODO.
// Top module: lin_node

`timescale 1ns/1ps

module lin_node_regs (
    input         clk,
    input         rst_n,
    input  [31:0] reg_addr,
    input         reg_we,
    input  [31:0] reg_wdata,
    output reg [31:0] reg_rdata
);

    // Register declarations
    reg [7:0] MEMMAP_LOW_000000B8; // offset 0xB8 (ro)
    reg [7:0] MEMMAP_HIGH_000000FF; // offset 0xFF (ro)

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            MEMMAP_LOW_000000B8 <= 8'b0;
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
