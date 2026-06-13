// Auto-generated register-file skeleton.
// Address decode + read/write hooks are stubbed; behavior is TODO.
// Top module: NVMe_Controller

`timescale 1ns/1ps

module NVMe_Controller_regs (
    input         clk,
    input         rst_n,
    input  [31:0] reg_addr,
    input         reg_we,
    input  [31:0] reg_wdata,
    output reg [31:0] reg_rdata
);

    // Register declarations
    reg [63:0] CAP; // offset  (ro)
    reg [31:0] VS; // offset  (ro)
    reg [31:0] INTMS; // offset  (rws)
    reg [31:0] INTMC; // offset  (rwc)
    reg [31:0] CC; // offset  (rw)
    reg [31:0] CSTS; // offset  (ro/rwc)
    reg [31:0] NSSR; // offset  (rw)
    reg [31:0] AQA; // offset  (rw)
    reg [63:0] ASQ; // offset  (rw)
    reg [63:0] ACQ; // offset  (rw)
    reg [31:0] CMBLOC; // offset  (ro)
    reg [31:0] CMBSZ; // offset  (ro)
    reg [31:0] BPINFO; // offset  (ro)
    reg [31:0] BPRSEL; // offset  (rw)
    reg [63:0] BPMBL; // offset  (rw)
    reg [63:0] CMBMSC; // offset  (rw)
    reg [31:0] CMBSTS; // offset  (ro)
    reg [31:0] PMRCAP; // offset  (ro)
    reg [31:0] PMRCTL; // offset  (rw)
    reg [31:0] PMRSTS; // offset  (ro)
    reg [31:0] PMREBS; // offset  (ro)
    reg [31:0] PMRSWTP; // offset  (ro)
    reg [63:0] PMRMSC; // offset  (rw)
    reg [31:0] SQ0TDBL; // offset  (rw)
    reg [31:0] CQ0HDBL; // offset  (rw)
    reg [31:0] SQyTDBL; // offset  (rw)
    reg [31:0] CQyHDBL; // offset  (rw)

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            CAP <= 64'b0;
            VS <= 32'b0;
            INTMS <= 32'b0;
            INTMC <= 32'b0;
            CC <= 32'b0;
            CSTS <= 32'b0;
            NSSR <= 32'b0;
            AQA <= 32'b0;
            ASQ <= 64'b0;
            ACQ <= 64'b0;
            CMBLOC <= 32'b0;
            CMBSZ <= 32'b0;
            BPINFO <= 32'b0;
            BPRSEL <= 32'b0;
            BPMBL <= 64'b0;
            CMBMSC <= 64'b0;
            CMBSTS <= 32'b0;
            PMRCAP <= 32'b0;
            PMRCTL <= 32'b0;
            PMRSTS <= 32'b0;
            PMREBS <= 32'b0;
            PMRSWTP <= 32'b0;
            PMRMSC <= 64'b0;
            SQ0TDBL <= 32'b0;
            CQ0HDBL <= 32'b0;
            SQyTDBL <= 32'b0;
            CQyHDBL <= 32'b0;
        end else if (reg_we) begin
            // TODO — address decode (per L4 offsets)
        end
    end

    // Read mux (TODO — match the offsets above)
    always @(*) begin
        reg_rdata = 32'b0;
    end

endmodule
