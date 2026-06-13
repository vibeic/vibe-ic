//      // verilator_coverage annotation
        /*
         * serv_mem_if.v : SERV memory interface
         *
         * SPDX-FileCopyrightText: 2018 Olof Kindgren <olof@award-winning.me>
         * SPDX-License-Identifier: ISC
         */
        `default_nettype none
        module serv_mem_if
          #(
            parameter [0:0] WITH_CSR = 1,
            parameter	    W = 1,
            parameter	    B = W-1
          )
          (
 200008    input wire 	     i_clk,
           //State
 005208    input wire [1:0]  i_bytecnt,
 001733    input wire [1:0]  i_lsb,
 002600    output wire 	     o_misalign,
           //Control
 000579    input wire 	     i_signed,
 000288    input wire 	     i_word,
 001156    input wire 	     i_half,
           //MDU
%000000    input wire 	     i_mdu_op,
           //Data
 040089    input wire [B:0] i_bufreg2_q,
 015637    output wire [B:0] o_rd,
           //External interface
 001157    output wire [3:0] o_wb_sel);
        
 015637    reg signbit;
        
 004634    wire dat_valid =
        	i_mdu_op |
        	i_word |
        	(i_bytecnt == 2'b00) |
        	(i_half & !i_bytecnt[1]);
        
           assign o_rd = dat_valid ? i_bufreg2_q : {W{i_signed & signbit}};
        
           assign o_wb_sel[3] = (i_lsb == 2'b11) | i_word | (i_half & i_lsb[1]);
           assign o_wb_sel[2] = (i_lsb == 2'b10) | i_word;
           assign o_wb_sel[1] = (i_lsb == 2'b01) | i_word | (i_half & !i_lsb[1]);
           assign o_wb_sel[0] = (i_lsb == 2'b00);
        
 100003    always @(posedge i_clk) begin
 046343       if (dat_valid)
 053660         signbit <= i_bufreg2_q[B];
           end
        
           /*
            mem_misalign is checked after the init stage to decide whether to do a data
            bus transaction or go to the trap state. It is only guaranteed to be correct
            at this time
            */
           assign o_misalign = WITH_CSR & ((i_lsb[0] & (i_word | i_half)) | (i_lsb[1] & i_word));
        
        endmodule
        
