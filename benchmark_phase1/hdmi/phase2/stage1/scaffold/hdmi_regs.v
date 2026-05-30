// Auto-generated register-file skeleton.
// Address decode + read/write hooks are stubbed; behavior is TODO.
// Top module: hdmi

`timescale 1ns/1ps

module hdmi_regs (
    input         clk,
    input         rst_n,
    input  [31:0] reg_addr,
    input         reg_we,
    input  [31:0] reg_wdata,
    output reg [31:0] reg_rdata
);

    // Register declarations
    reg [15:0] VEN_ID; // offset  (r)
    reg [15:0] DEV_ID; // offset  (r)
    reg [7:0] REV_ID; // offset  (r)
    reg [23:0] RESERVED_07_05; // offset  (r)
    reg [7:0] CTL_1_MODE; // offset  (rw)
    reg [7:0] CTL_2_MODE; // offset  (rw)
    reg [7:0] CTL_3_MODE; // offset  (rw)
    reg [7:0] CFG; // offset  (r)
    reg [7:0] DE_DLY; // offset  (rw)
    reg [7:0] DE_CTL; // offset  (rw)
    reg [7:0] DE_TOP; // offset  (rw)
    reg [10:0] DE_CNT; // offset  (rw)
    reg [10:0] DE_LIN; // offset  (rw)
    reg [10:0] H_RES; // offset  (r)
    reg [10:0] V_RES; // offset  (r)

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            VEN_ID <= 16'b0;
            DEV_ID <= 16'b0;
            REV_ID <= 8'b0;
            RESERVED_07_05 <= 24'b0;
            CTL_1_MODE <= 8'b0;
            CTL_2_MODE <= 8'b0;
            CTL_3_MODE <= 8'b0;
            CFG <= 8'b0;
            DE_DLY <= 8'b0;
            DE_CTL <= 8'b0;
            DE_TOP <= 8'b0;
            DE_CNT <= 11'b0;
            DE_LIN <= 11'b0;
            H_RES <= 11'b0;
            V_RES <= 11'b0;
        end else if (reg_we) begin
            // TODO — address decode (per L4 offsets)
        end
    end

    // Read mux (TODO — match the offsets above)
    always @(*) begin
        reg_rdata = 32'b0;
    end

endmodule
