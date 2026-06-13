//      // verilator_coverage annotation
        /*
         * serv_ctrl.v : SERV module for updating program counter
         *
         * SPDX-FileCopyrightText: 2018 Olof Kindgren <olof@award-winning.me>
         * SPDX-License-Identifier: ISC
         */
        `default_nettype none
        module serv_ctrl
          #(parameter RESET_STRATEGY = "MINI",
            parameter RESET_PC = 32'd0,
            parameter WITH_CSR = 1,
            parameter W = 1,
            parameter B = W-1
          )
          (
 200008    input wire 	     clk,
%000002    input wire 	     i_rst,
           //State
 003475    input wire 	     i_pc_en,
 005209    input wire 	     i_cnt12to31,
 005210    input wire 	     i_cnt0,
 005210    input wire        i_cnt1,
 005210    input wire 	     i_cnt2,
           //Control
 001156    input wire 	     i_jump,
 000288    input wire 	     i_jal_or_jalr,
%000000    input wire 	     i_utype,
%000001    input wire 	     i_pc_rel,
%000000    input wire 	     i_trap,
%000000    input wire        i_iscomp,
           //Data
 002605    input wire [B:0] i_imm,
 003466    input wire [B:0] i_buf,
 000146    input wire [B:0] i_csr_pc,
 000576    output wire [B:0] o_rd,
 008966    output wire [B:0] o_bad_pc,
           //External
 004632    output reg [31:0] o_ibus_adr);
        
 005500    wire [B:0] pc_plus_4;
 001738    wire       pc_plus_4_cy;
 001738    reg 	      pc_plus_4_cy_r;
 001738    wire [B:0] pc_plus_4_cy_r_w;
 008966    wire [B:0] pc_plus_offset;
 001444    wire       pc_plus_offset_cy;
 001444    reg	      pc_plus_offset_cy_r;
 001444    wire [B:0] pc_plus_offset_cy_r_w;
 008966    wire [B:0] pc_plus_offset_aligned;
 005210    wire [B:0] plus_4;
        
 004632    wire [B:0] pc = o_ibus_adr[B:0];
        
 006368    wire [B:0] new_pc;
        
 004632    wire [B:0] offset_a;
 003466    wire [B:0] offset_b;
        
          /*  If i_iscomp=1: increment pc by 2 else increment pc by 4  */
        
           generate
              if (W == 1) begin : gen_plus_4_w_eq_1
        	 assign plus_4 = i_iscomp ? i_cnt1 : i_cnt2;
              end else if (W == 4) begin : gen_plus_4_w_eq_4
        	 assign plus_4 = (i_cnt0 | i_cnt1) ? (i_iscomp ? 2 : 4) : 0;
              end
           endgenerate
        
           assign o_bad_pc = pc_plus_offset_aligned;
        
           assign {pc_plus_4_cy,pc_plus_4} = pc+plus_4+pc_plus_4_cy_r_w;
        
           generate
              if (|WITH_CSR) begin : gen_csr
        	 if (W == 1) begin : gen_new_pc_w_eq_1
        	    assign new_pc = i_trap ? (i_csr_pc & !(i_cnt0 || i_cnt1)) : i_jump ? pc_plus_offset_aligned : pc_plus_4;
                 end else if (W == 4) begin : gen_new_pc_w_eq_4
        	    assign new_pc = i_trap ? (i_csr_pc & ((i_cnt0 || i_cnt1) ? 4'b1100 : 4'b1111)) : i_jump ? pc_plus_offset_aligned : pc_plus_4;
        	 end
              end else begin : gen_no_csr
        	 assign new_pc = i_jump ? pc_plus_offset_aligned : pc_plus_4;
              end
           endgenerate
           assign o_rd  = ({W{i_utype}} & pc_plus_offset_aligned) | (pc_plus_4 & {W{i_jal_or_jalr}});
        
           assign offset_a = {W{i_pc_rel}} & pc;
           assign offset_b = i_utype ? (i_imm & {W{i_cnt12to31}}) : i_buf;
           assign {pc_plus_offset_cy,pc_plus_offset} = offset_a+offset_b+pc_plus_offset_cy_r_w;
        
           generate
           if (W>1) begin : gen_w_gt_1
        	 assign pc_plus_offset_aligned[B:1] = pc_plus_offset[B:1];
        	 assign pc_plus_offset_cy_r_w[B:1] = {B{1'b0}};
        	 assign pc_plus_4_cy_r_w[B:1] = {B{1'b0}};
           end
           endgenerate
        
           assign pc_plus_offset_aligned[0] = pc_plus_offset[0] & !i_cnt0;
           assign pc_plus_offset_cy_r_w[0] = pc_plus_offset_cy_r;
           assign pc_plus_4_cy_r_w[0] = pc_plus_4_cy_r;
        
%000001    initial if (RESET_STRATEGY == "NONE") o_ibus_adr = RESET_PC;
        
 100003    always @(posedge clk) begin
 100003       pc_plus_4_cy_r <= i_pc_en & pc_plus_4_cy;
 100003       pc_plus_offset_cy_r <= i_pc_en & pc_plus_offset_cy;
        
 100003       if (RESET_STRATEGY == "NONE") begin
%000000 	 if (i_pc_en)
%000000 	   o_ibus_adr <= {new_pc, o_ibus_adr[31:W]};
 100003       end else begin
 044401 	 if (i_pc_en | i_rst)
 055602 	   o_ibus_adr <= i_rst ? RESET_PC : {new_pc, o_ibus_adr[31:W]};
              end
           end
        endmodule
        
