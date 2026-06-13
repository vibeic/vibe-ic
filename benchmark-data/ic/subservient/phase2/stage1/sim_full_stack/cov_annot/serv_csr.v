//      // verilator_coverage annotation
        /*
         * serv_csr.v : SERV module for handling CSR registers
         *
         * SPDX-FileCopyrightText: 2018 Olof Kindgren <olof@award-winning.me>
         * SPDX-License-Identifier: ISC
         */
        `default_nettype none
        module serv_csr
          #(
            parameter RESET_STRATEGY = "MINI",
            parameter W = 1,
            parameter B = W-1
          )
          (
 200008    input wire 	    i_clk,
%000002    input wire 	    i_rst,
           //State
 003476    input wire 	    i_trig_irq,
 003765    input wire 	    i_en,
 005210    input wire 	    i_cnt0to3,
 005210    input wire 	    i_cnt3,
 005210    input wire 	    i_cnt7,
 005210    input wire 	    i_cnt11,
 005210    input wire 	    i_cnt12,
 005208    input wire 	    i_cnt_done,
 001157    input wire 	    i_mem_op,
%000000    input wire 	    i_mtip,
%000000    input wire 	    i_trap,
%000000    output reg 	    o_new_irq,
           //Control
%000000    input wire 	    i_e_op,
 001447    input wire 	    i_ebreak,
 001158    input wire 	    i_mem_cmd,
%000000    input wire 	    i_mstatus_en,
%000000    input wire 	    i_mie_en,
%000000    input wire 	    i_mcause_en,
 000288    input wire [1:0] i_csr_source,
%000000    input wire 	    i_mret,
 000578    input wire 	    i_csr_d_sel,
           //Data
%000000    input wire 	[B:0]    i_rf_csr_out,
 000868    output wire 	[B:0]    o_csr_in,
 000578    input wire 	[B:0]    i_csr_imm,
 002462    input wire 	[B:0]    i_rs1,
%000000    output wire 	[B:0]    o_q);
        
           localparam [1:0]
             CSR_SOURCE_CSR = 2'b00,
             CSR_SOURCE_EXT = 2'b01,
             CSR_SOURCE_SET = 2'b10,
             CSR_SOURCE_CLR = 2'b11;
        
%000000    reg 		    mstatus_mie;
%000000    reg 		    mstatus_mpie;
%000000    reg 		    mie_mtie;
        
%000000    reg 		mcause31;
%000000    reg [3:0] 	mcause3_0;
%000000    wire [B:0]	mcause;
        
 000868    wire [B:0]	csr_in;
%000000    wire [B:0]	csr_out;
        
%000000    reg 		timer_irq_r;
        
 002894    wire [B:0]	d = i_csr_d_sel ? i_csr_imm : i_rs1;
        
           assign csr_in = (i_csr_source == CSR_SOURCE_EXT) ? d :
        		   (i_csr_source == CSR_SOURCE_SET) ? csr_out | d :
        		   (i_csr_source == CSR_SOURCE_CLR) ? csr_out & ~d :
        		   (i_csr_source == CSR_SOURCE_CSR) ? csr_out :
        		   {W{1'bx}};
        
 005210    wire [B:0]	mstatus;
        
           generate
              if (W==1) begin : gen_mstatus_w1
        	 assign mstatus = ((mstatus_mie & i_cnt3) | (i_cnt11 | i_cnt12));
              end else if (W==4) begin : gen_mstatus_w4
        	 assign mstatus = {i_cnt11 | (mstatus_mie & i_cnt3), 2'b00, i_cnt12};
              end
           endgenerate
        
           assign csr_out = ({W{i_mstatus_en & i_en}} & mstatus) |
        		    i_rf_csr_out |
        		    ({W{i_mcause_en & i_en}} & mcause);
        
           assign o_q = csr_out;
        
%000000    wire 	timer_irq = i_mtip & mstatus_mie & mie_mtie;
        
           assign mcause = i_cnt0to3 ? mcause3_0[B:0] : //[3:0]
        		   i_cnt_done ? {mcause31,{B{1'b0}}} //[31]
        		   : {W{1'b0}};
        
           assign o_csr_in = csr_in;
        
 100003    always @(posedge i_clk) begin
 001738       if (i_trig_irq) begin
 001738 	 timer_irq_r <= timer_irq;
 001738 	 o_new_irq   <= timer_irq & !timer_irq_r;
              end
        
 100003       if (i_mie_en & i_cnt7)
%000000 	mie_mtie <= csr_in[B];
        
              /*
               The mie bit in mstatus gets updated under three conditions
        
               When a trap is taken, the bit is cleared
               During an mret instruction, the bit is restored from mpie
               During a mstatus CSR access instruction it's assigned when
                bit 3 gets updated
        
               These conditions are all mutually exclusive
               */
 100003       if ((i_trap & i_cnt_done) | i_mstatus_en & i_cnt3 & i_en | i_mret)
%000000 	mstatus_mie <= !i_trap & (i_mret ?  mstatus_mpie : csr_in[B]);
        
              /*
               Note: To save resources mstatus_mpie (mstatus bit 7) is not
               readable or writable from sw
               */
 100003       if (i_trap & i_cnt_done)
%000000 	mstatus_mpie <= mstatus_mie;
        
              /*
               The four lowest bits in mcause hold the exception code
        
               These bits get updated under three conditions
        
               During an mcause CSR access function, they are assigned when
               bits 0 to 3 gets updated
        
               During an external interrupt the exception code is set to
               7, since SERV only support timer interrupts
        
               During an exception, the exception code is assigned to indicate
               if it was caused by an ebreak instruction (3),
               ecall instruction (11), misaligned load (4), misaligned store (6)
               or misaligned jump (0)
        
               The expressions below are derived from the following truth table
               irq  => 0111 (timer=7)
               e_op => x011 (ebreak=3, ecall=11)
               mem  => 01x0 (store=6, load=4)
               ctrl => 0000 (jump=0)
               */
 100003       if (i_mcause_en & i_en & i_cnt0to3 | (i_trap & i_cnt_done)) begin
%000000 	 mcause3_0[3] <= (i_e_op & !i_ebreak) | (!i_trap & csr_in[B]);
%000000 	 mcause3_0[2] <= o_new_irq | i_mem_op | (!i_trap & ((W == 1) ? mcause3_0[3] : csr_in[(W == 1) ? 0 : 2]));
%000000 	 mcause3_0[1] <= o_new_irq | i_e_op | (i_mem_op & i_mem_cmd) | (!i_trap & ((W == 1) ? mcause3_0[2] : csr_in[(W == 1) ? 0 : 1]));
%000000 	 mcause3_0[0] <= o_new_irq | i_e_op | (!i_trap & ((W == 1) ? mcause3_0[1] : csr_in[0]));
              end
 100003       if (i_mcause_en & i_cnt_done | i_trap)
%000000 	mcause31 <= i_trap ? o_new_irq : csr_in[B];
%000003       if (i_rst)
%000000 	if (RESET_STRATEGY != "NONE") begin
%000003 	   o_new_irq <= 1'b0;
%000003 	   mie_mtie <= 1'b0;
        	end
           end
        
        endmodule
        
