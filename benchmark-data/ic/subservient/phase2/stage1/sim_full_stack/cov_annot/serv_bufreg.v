//      // verilator_coverage annotation
        /*
         * serv_bufreg.v : SERV buffer register for load/store address and shift data
         *
         * SPDX-FileCopyrightText: 2019 Olof Kindgren <olof@award-winning.me>
         * SPDX-License-Identifier: ISC
         */
        module serv_bufreg #(
              parameter [0:0] MDU = 0,
              parameter W = 1,
              parameter B = W-1
        )(
 200008    input wire 	      i_clk,
           //State
 005210    input wire 	      i_cnt0,
 005210    input wire 	      i_cnt1,
 005208    input wire 	      i_cnt_done,
 001734    input wire 	      i_en,
 002894    input wire 	      i_init,
%000000    input wire           i_mdu_op,
 001733    output wire [1:0]    o_lsb,
           //Control
 001157    input wire 	      i_rs1_en,
 001160    input wire 	      i_imm_en,
 001156    input wire 	      i_clr_lsb,
 001159    input wire 	      i_shift_op,
 000578    input wire 	      i_right_shift_op,
 012033    input wire [2:0]   i_shamt,
 000289    input wire 	      i_sh_signed,
           //Data
 002462    input wire [B:0] i_rs1,
 002605    input wire [B:0] i_imm,
 003466    output wire [B:0] o_q,
           //External
 001733    output wire [31:0] o_dbus_adr,
           //Extension
 001733    output wire [31:0] o_ext_rs1);
        
%000000    wire		      c;
 005926    wire [B:0]	      q;
%000000    reg [B:0]	      c_r;
 001733    reg [31:0]	      data;
 002888    wire [B:0]	      clr_lsb;
        
           assign clr_lsb[0] = i_cnt0 & i_clr_lsb;
        
           generate
              if (W > 1) begin : gen_clr_lsb_w_gt_1
                 assign  clr_lsb[B:1] = {B{1'b0}};
              end
           endgenerate
        
           assign {c,q} = {1'b0,(i_rs1 & {W{i_rs1_en}})} + {1'b0,(i_imm & {W{i_imm_en}} & ~clr_lsb)} + c_r;
        
 100003    always @(posedge i_clk) begin
              //Make sure carry is cleared before loading new data
 100003       c_r    <= {W{1'b0}};
 100003       c_r[0] <= c & i_en;
           end
        
           generate
              if (W == 1) begin : gen_w_eq_1
 100003 	 always @(posedge i_clk) begin
 049155 	    if (i_en)
 050848 	      data[31:2] <= {i_init ? q : {W{data[31] & i_sh_signed}}, data[31:3]};
        
 024838 	    if (i_init ? (i_cnt0 | i_cnt1) : i_en)
 024838 	      data[1:0] <= {i_init ? q : data[2], data[1]};
        	 end
        	 assign o_lsb = (MDU & i_mdu_op) ? 2'b00 : data[1:0];
        	 assign o_q = data[0] & {W{i_en}};
              end else if (W == 4) begin : gen_lsb_w_4
        	 reg [1:0] lsb;
        	 reg [W-2:0] data_tail;
        
        	 wire [2:0] shift_amount
        	   = !i_shift_op ? 3'd3 :
        	     i_right_shift_op ? (3'd3+{1'b0,i_shamt[1:0]}) :
        	     ({1'b0,~i_shamt[1:0]});
        
        	 always @(posedge i_clk) begin
                    if (i_en)
                      if (i_cnt0) lsb <= q[1:0];
        	    if (i_en)
                      data <= {i_init ? q : {W{i_sh_signed & data[31]}}, data[31:W]};
        	    if (i_en)
        	      data_tail <= data[B:1] & {B{~i_cnt_done}};
        	 end
        
        	 wire [2*W+B-2:0] muxdata = {data[W+B-1:0],data_tail};
        	 wire [B:0]	  muxout = muxdata[{1'b0,shift_amount}+:W];
        
        	 assign o_lsb = (MDU & i_mdu_op) ? 2'b00 : lsb;
        	 assign o_q = i_en ? muxout : {W{1'b0}};
              end
           endgenerate
        
        
           assign o_dbus_adr = {data[31:2], 2'b00};
           assign o_ext_rs1  = data;
        
        endmodule
        
