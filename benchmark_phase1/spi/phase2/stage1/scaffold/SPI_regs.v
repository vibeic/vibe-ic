// Auto-generated register-file skeleton.
// Address decode + read/write hooks are stubbed; behavior is TODO.
// Top module: SPI

`timescale 1ns/1ps

module SPI_regs (
    input         clk,
    input         rst_n,
    input  [31:0] reg_addr,
    input         reg_we,
    input  [31:0] reg_wdata,
    output reg [31:0] reg_rdata
);

    // Register declarations
    reg [7:0] SPICR1; // offset $___0 (read / write (anytime))
    reg [7:0] SPICR2; // offset $___1 (read / write (anytime; reserved bits writes ignored))
    reg [7:0] SPIBR; // offset $___2 (read / write (anytime; reserved bits writes ignored))
    reg [7:0] SPISR; // offset $___3 (read; writes have no effect)
    reg [7:0] Reserved_4; // offset $___4 (writes ignored; reads return all zeros.)
    reg [7:0] SPIDR; // offset $___5 (read (normally only when spif set) / write (anytime))
    reg [7:0] Reserved_6; // offset $___6 (writes ignored; reads return all zeros.)
    reg [7:0] Reserved_7; // offset $___7 (writes ignored; reads return all zeros.)

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            SPICR1 <= 8'b0;
            SPICR2 <= 8'b0;
            SPIBR <= 8'b0;
            SPISR <= 8'b0;
            Reserved_4 <= 8'b0;
            SPIDR <= 8'b0;
            Reserved_6 <= 8'b0;
            Reserved_7 <= 8'b0;
        end else if (reg_we) begin
            // TODO — address decode (per L4 offsets)
        end
    end

    // Read mux (TODO — match the offsets above)
    always @(*) begin
        reg_rdata = 32'b0;
    end

endmodule
