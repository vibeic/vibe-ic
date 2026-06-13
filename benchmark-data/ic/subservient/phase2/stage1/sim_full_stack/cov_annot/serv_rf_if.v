//      // verilator_coverage annotation
        /*
         * serv_rf_if.v : SERV register file interface
         *
         * SPDX-FileCopyrightText: 2019 Olof Kindgren <olof@award-winning.me>
         * SPDX-License-Identifier: ISC
         */
        `default_nettype none
        module serv_rf_if
          #(parameter WITH_CSR = 1,
            parameter W = 1,
            parameter B = W-1
          )
          (//RF Interface
 003765    input wire 		      i_cnt_en,
%000000    output wire [4+WITH_CSR:0] o_wreg0,
%000001    output wire [4+WITH_CSR:0] o_wreg1,
 001741    output wire 		      o_wen0,
%000000    output wire 		      o_wen1,
 004058    output wire [B:0]  o_wdata0,
 000868    output wire [B:0]  o_wdata1,
%000000    output wire [4+WITH_CSR:0] o_rreg0,
%000000    output wire [4+WITH_CSR:0] o_rreg1,
 002462    input wire  [B:0] i_rdata0,
 000146    input wire  [B:0] i_rdata1,
        
           //Trap interface
%000000    input wire 		      i_trap,
%000000    input wire 		      i_mret,
 004632    input wire [B:0] i_mepc,
 001156    input wire                      i_mtval_pc,
 003466    input wire [B:0] i_bufreg_q,
 008966    input wire [B:0] i_bad_pc,
 000146    output wire [B:0] o_csr_pc,
           //CSR interface
%000000    input wire 		      i_csr_en,
 001157    input wire [1:0] 	      i_csr_addr,
 000868    input wire [B:0] i_csr,
%000000    output wire [B:0] o_csr,
           //RD write port
 001447    input wire 		      i_rd_wen,
 000291    input wire [4:0] 	      i_rd_waddr,
 000576    input wire [B:0] i_ctrl_rd,
 006942    input wire [B:0] i_alu_rd,
 001159    input wire 		      i_rd_alu_en,
%000000    input wire [B:0] i_csr_rd,
%000000    input wire 		      i_rd_csr_en,
 015637    input wire [B:0] i_mem_rd,
 001448    input wire 		      i_rd_mem_en,
        
           //RS1 read port
 000288    input wire [4:0] 	      i_rs1_raddr,
 002462    output wire [B:0] o_rs1,
           //RS2 read port
 001447    input wire [4:0] 	      i_rs2_raddr,
 000146    output wire [B:0] o_rs2);
        
        
           /*
            ********** Write side ***********
            */
        
 001159    wire 	     rd_wen = i_rd_wen & (|i_rd_waddr);
        
           generate
           if (|WITH_CSR) begin : gen_csr
           wire [B:0] rd =
               {W{i_rd_alu_en}} & i_alu_rd |
               {W{i_rd_csr_en}} & i_csr_rd |
               {W{i_rd_mem_en}} & i_mem_rd |
                               i_ctrl_rd;
        
           wire [B:0]  mtval = i_mtval_pc ? i_bad_pc : i_bufreg_q;
        
           assign 	     o_wdata0 = i_trap ? mtval  : rd;
           assign	     o_wdata1 = i_trap ? i_mepc : i_csr;
        
           /* Port 0 handles writes to mtval during traps and rd otherwise
            * Port 1 handles writes to mepc during traps and csr accesses otherwise
            *
            * GPR registers are mapped to address 0-31 (bits 0xxxxx).
            * Following that are four CSR registers
            * mscratch 100000
            * mtvec    100001
            * mepc     100010
            * mtval    100011
            */
        
           assign o_wreg0 = i_trap ? {6'b100011} : {1'b0,i_rd_waddr};
           assign o_wreg1 = i_trap ? {6'b100010} : {4'b1000,i_csr_addr};
        
           assign       o_wen0 = i_cnt_en & (i_trap | rd_wen);
           assign       o_wen1 = i_cnt_en & (i_trap | i_csr_en);
        
           /*
            ********** Read side ***********
            */
        
           //0 : RS1
           //1 : RS2 / CSR
        
           assign o_rreg0 = {1'b0, i_rs1_raddr};
        
           /*
            The address of the second read port (o_rreg1) can get assigned from four
            different sources
        
            Normal operations : i_rs2_raddr
            CSR access        : i_csr_addr
            trap              : MTVEC
            mret              : MEPC
        
            Address 0-31 in the RF are assigned to the GPRs. After that follows the four
            CSRs on addresses 32-35
        
            32 MSCRATCH
            33 MTVEC
            34 MEPC
            35 MTVAL
        
            The expression below is an optimized version of this logic
            */
           wire sel_rs2 = !(i_trap | i_mret | i_csr_en);
           assign o_rreg1 = {~sel_rs2,
        		     i_rs2_raddr[4:2] & {3{sel_rs2}},
        		     {1'b0,i_trap} | {i_mret,1'b0} | ({2{i_csr_en}} & i_csr_addr) | ({2{sel_rs2}} & i_rs2_raddr[1:0])};
        
           assign o_rs1 = i_rdata0;
           assign o_rs2 = i_rdata1;
           assign o_csr = i_rdata1 & {W{i_csr_en}};
           assign o_csr_pc = i_rdata1;
        
           end else begin : gen_no_csr
              wire [B:0] rd = (i_ctrl_rd) |
                  i_alu_rd  & {W{i_rd_alu_en}} |
                  i_mem_rd  & {W{i_rd_mem_en}};
        
              assign 	     o_wdata0 = rd;
              assign	     o_wdata1 = {W{1'b0}};
        
              assign o_wreg0 = i_rd_waddr;
              assign o_wreg1 = 5'd0;
        
              assign       o_wen0 = i_cnt_en & rd_wen;
              assign       o_wen1 = 1'b0;
        
           /*
            ********** Read side ***********
            */
        
              assign o_rreg0 = i_rs1_raddr;
              assign o_rreg1 = i_rs2_raddr;
        
              assign o_rs1 = i_rdata0;
              assign o_rs2 = i_rdata1;
              assign o_csr = {W{1'b0}};
              assign o_csr_pc = {W{1'b0}};
           end // else: !if(WITH_CSR)
           endgenerate
        endmodule
        
