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
    reg [31:0] ABORT; // offset 0x0 (write) (write-only)
    reg [31:0] IDCODE_DPIDR; // offset 0x0 (read) (read-only)
    reg [31:0] CTRL_STAT; // offset 0x4 (bank 0) (read/write)
    reg [31:0] SELECT; // offset 0x8 (write) (write-only)
    reg [31:0] RDBUFF; // offset 0xC (read) (read-only)
    reg [31:0] TARGETID; // offset 0x4 (bank 2 — ADIv5.1+) (read-only)
    reg [31:0] DLPIDR; // offset 0x4 (bank 3 — ADIv5.1+ multi-drop) (read-only)
    reg [31:0] EVENTSTAT; // offset 0x4 (bank 4 — ADIv5.1+) (read-only)
    reg [31:0] CSW; // offset 0x00 (read/write)
    reg [31:0] TAR; // offset 0x04 (read/write)
    reg [31:0] DRW; // offset 0x0C (read/write)
    reg [31:0] BASE; // offset 0xF8 (read-only)
    reg [31:0] IDR; // offset 0xFC (read-only)

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ABORT <= 32'b0;
            IDCODE_DPIDR <= 32'b0;
            CTRL_STAT <= 32'b0;
            SELECT <= 32'b0;
            RDBUFF <= 32'b0;
            TARGETID <= 32'b0;
            DLPIDR <= 32'b0;
            EVENTSTAT <= 32'b0;
            CSW <= 32'b0;
            TAR <= 32'b0;
            DRW <= 32'b0;
            BASE <= 32'b0;
            IDR <= 32'b0;
        end else if (reg_we) begin
            // TODO — address decode (per L4 offsets)
        end
    end

    // Read mux (TODO — match the offsets above)
    always @(*) begin
        reg_rdata = 32'b0;
    end

endmodule
