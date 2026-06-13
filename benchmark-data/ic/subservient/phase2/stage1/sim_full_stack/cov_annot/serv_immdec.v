//      // verilator_coverage annotation
        /*
         * serv_immdec.v : SERV module for decoding immediates from instruction words
         *
         * SPDX-FileCopyrightText: 2020 Olof Kindgren <olof@award-winning.me>
         * SPDX-License-Identifier: ISC
         */
        `default_nettype none
        module serv_immdec
          #(parameter SHARED_RFADDR_IMM_REGS = 1,
            parameter W = 1)
          (
 200008    input wire 	     i_clk,
           //State
 003765    input wire 	     i_cnt_en,
 005208    input wire 	     i_cnt_done,
           //Control
%000001    input wire [3:0]  i_immdec_en,
%000000    input wire 	     i_csr_imm_en,
 000289    input wire [3:0]  i_ctrl,
 000291    output wire [4:0] o_rd_addr,
 000288    output wire [4:0] o_rs1_addr,
 001447    output wire [4:0] o_rs2_addr,
           //Data
 000578    output wire [W-1:0] o_csr_imm,
 002605    output wire [W-1:0] o_imm,
           //External
 003476    input wire 	     i_wb_en,
 000288    input wire [31:7] i_wb_rdt);
        
        generate
           if (W == 1) begin : gen_immdec_w_eq_1
           reg 		     imm31;
        
           reg [8:0]  imm19_12_20;
           reg 	      imm7;
           reg [5:0]  imm30_25;
           reg [4:0]  imm24_20;
           reg [4:0]  imm11_7;
        
           assign o_csr_imm = imm19_12_20[4];
        
           wire       signbit = imm31 & !i_csr_imm_en;
        
              if (SHARED_RFADDR_IMM_REGS) begin : gen_shared_imm_regs
        	 assign o_rs1_addr = imm19_12_20[8:4];
        	 assign o_rs2_addr = imm24_20;
        	 assign o_rd_addr  = imm11_7;
        
 100003 	 always @(posedge i_clk) begin
 001738 	    if (i_wb_en) begin
        	       /* CSR immediates are always zero-extended, hence clear the signbit */
 001738 	       imm31     <= i_wb_rdt[31];
        	    end
 010954 	    if (i_wb_en | (i_cnt_en & i_immdec_en[1]))
 010954 	      imm19_12_20 <= i_wb_en ? {i_wb_rdt[19:12],i_wb_rdt[20]} : {i_ctrl[3] ? signbit : imm24_20[0], imm19_12_20[8:1]};
 014922 	    if (i_wb_en | (i_cnt_en))
 085081 	      imm7        <= i_wb_en ? i_wb_rdt[7]                    : signbit;
        
 014922 	    if (i_wb_en | (i_cnt_en & i_immdec_en[3]))
 085081 	      imm30_25    <= i_wb_en ? i_wb_rdt[30:25] : {i_ctrl[2] ? imm7 : i_ctrl[1] ? signbit : imm19_12_20[0], imm30_25[5:1]};
        
 038809 	    if (i_wb_en | (i_cnt_en & i_immdec_en[2]))
 038809 	      imm24_20    <= i_wb_en ? i_wb_rdt[24:20] : {imm30_25[0], imm24_20[4:1]};
        
 048010 	    if (i_wb_en | (i_cnt_en & i_immdec_en[0]))
 048010 	      imm11_7     <= i_wb_en ? i_wb_rdt[11:7] : {imm30_25[0], imm11_7[4:1]};
        	 end
              end else begin : gen_separate_imm_regs
        	 reg [4:0]  rd_addr;
        	 reg [4:0]  rs1_addr;
        	 reg [4:0]  rs2_addr;
        
        	 assign o_rd_addr  = rd_addr;
        	 assign o_rs1_addr = rs1_addr;
        	 assign o_rs2_addr = rs2_addr;
        	 always @(posedge i_clk) begin
        	    if (i_wb_en) begin
        	       /* CSR immediates are always zero-extended, hence clear the signbit */
        	       imm31       <= i_wb_rdt[31];
        	       imm19_12_20 <= {i_wb_rdt[19:12],i_wb_rdt[20]};
        	       imm7        <= i_wb_rdt[7];
        	       imm30_25    <= i_wb_rdt[30:25];
        	       imm24_20    <= i_wb_rdt[24:20];
        	       imm11_7     <= i_wb_rdt[11:7];
        
                       rd_addr  <= i_wb_rdt[11:7];
                       rs1_addr <= i_wb_rdt[19:15];
                       rs2_addr <= i_wb_rdt[24:20];
        	    end
        	    if (i_cnt_en) begin
        	       imm19_12_20 <= {i_ctrl[3] ? signbit : imm24_20[0], imm19_12_20[8:1]};
        	       imm7        <= signbit;
        	       imm30_25    <= {i_ctrl[2] ? imm7 : i_ctrl[1] ? signbit : imm19_12_20[0], imm30_25[5:1]};
        	       imm24_20    <= {imm30_25[0], imm24_20[4:1]};
        	       imm11_7     <= {imm30_25[0], imm11_7[4:1]};
        	    end
        	 end
              end
        
        	 assign o_imm = i_cnt_done ? signbit : i_ctrl[0] ? imm11_7[0] : imm24_20[0];
           end else begin : gen_immdec_w_eq_4
           reg [4:0]	     rd_addr;
           reg [4:0]	     rs1_addr;
           reg [4:0]	     rs2_addr;
        
           reg		     i31;
           reg		     i30;
           reg		     i29;
           reg		     i28;
           reg		     i27;
           reg		     i26;
           reg		     i25;
           reg		     i24;
           reg		     i23;
           reg		     i22;
           reg		     i21;
           reg		     i20;
           reg		     i19;
           reg		     i18;
           reg		     i17;
           reg		     i16;
           reg		     i15;
           reg		     i14;
           reg		     i13;
           reg		     i12;
           reg		     i11;
           reg		     i10;
           reg		     i9;
           reg		     i8;
           reg		     i7;
        
           reg		     i7_2;
           reg		     i20_2;
        
           wire		     signbit = i31 & !i_csr_imm_en;
        
           assign o_csr_imm[3] = i18;
           assign o_csr_imm[2] = i17;
           assign o_csr_imm[1] = i16;
           assign o_csr_imm[0] = i15;
        
           assign o_rd_addr  = rd_addr;
           assign o_rs1_addr = rs1_addr;
           assign o_rs2_addr = rs2_addr;
           always @(posedge i_clk) begin
              if (i_wb_en) begin
        	 //Common
        	 i31 <= i_wb_rdt[31];
        
        	 //Bit lane 3
        	 i19 <= i_wb_rdt[19];
        	 i15 <= i_wb_rdt[15];
        	 i20 <= i_wb_rdt[20];
        	 i7  <= i_wb_rdt[7];
        	 i27 <= i_wb_rdt[27];
        	 i23 <= i_wb_rdt[23];
        	 i10 <= i_wb_rdt[10];
        
        	 //Bit lane 2
        	 i22 <= i_wb_rdt[22];
        	 i9  <= i_wb_rdt[ 9];
        	 i26 <= i_wb_rdt[26];
        	 i30 <= i_wb_rdt[30];
        	 i14 <= i_wb_rdt[14];
        	 i18 <= i_wb_rdt[18];
        
        	 //Bit lane 1
        	 i21 <= i_wb_rdt[21];
        	 i8  <= i_wb_rdt[ 8];
        	 i25 <= i_wb_rdt[25];
        	 i29 <= i_wb_rdt[29];
        	 i13 <= i_wb_rdt[13];
        	 i17 <= i_wb_rdt[17];
        
        	 //Bit lane 0
        	 i11 <= i_wb_rdt[11];
        	 i7_2  <= i_wb_rdt[7 ];
        	 i20_2   <= i_wb_rdt[20];
        	 i24   <= i_wb_rdt[24];
        	 i28   <= i_wb_rdt[28];
        	 i12   <= i_wb_rdt[12];
        	 i16   <= i_wb_rdt[16];
        
                 rd_addr  <= i_wb_rdt[11:7];
                 rs1_addr <= i_wb_rdt[19:15];
                 rs2_addr <= i_wb_rdt[24:20];
              end
              if (i_cnt_en) begin
        	 //Bit lane 3
        	 i10 <= i27;
        	 i23 <= i27;
        	 i27 <= i_ctrl[2] ? i7 : i_ctrl[1] ? signbit : i20;
        	 i7  <= signbit;
        	 i20 <= i15;
        	 i15 <= i19;
        	 i19 <= i_ctrl[3] ? signbit : i23;
        
        	 //Bit lane 2
        	 i22 <= i26;
        	 i9  <= i26;
        	 i26 <= i30;
        	 i30 <= (i_ctrl[1] | i_ctrl[2]) ? signbit : i14;
        	 i14 <= i18;
        	 i18 <= i_ctrl[3] ? signbit : i22;
        
        	 //Bit lane 1
        	 i21 <= i25;
        	 i8  <= i25;
        	 i25 <= i29;
        	 i29 <= (i_ctrl[1] | i_ctrl[2]) ? signbit : i13;
        	 i13 <= i17;
        	 i17 <= i_ctrl[3] ? signbit : i21;
        
        	 //Bit lane 0
        	 i7_2  <= i11;
        	 i11   <= i28;
        	 i20_2   <= i24;
        	 i24   <= i28;
        	 i28   <= (i_ctrl[1] | i_ctrl[2]) ? signbit : i12;
        	 i12   <= i16;
        	 i16   <= i_ctrl[3] ? signbit : i20_2;
        
              end
           end
        
           assign o_imm[3] = (i_cnt_done ? signbit : (i_ctrl[0] ? i10 : i23));
           assign o_imm[2] = i_ctrl[0] ? i9 : i22;
           assign o_imm[1] = i_ctrl[0] ? i8 : i21;
           assign o_imm[0] = i_ctrl[0] ? i7_2 : i20_2;
        
           end
        endgenerate
        
        endmodule
        
