//      // verilator_coverage annotation
        /*
         * serv_rf_ram_if.v : Interface between SERV and SRAM-based RF storage
         *
         * SPDX-FileCopyrightText: 2019 Olof Kindgren <olof@award-winning.me>
         * SPDX-License-Identifier: ISC
         */
        `default_nettype none
        module serv_rf_ram_if
          #(//Data width. Adjust to preferred width of SRAM data interface
            parameter width=8,
        
            parameter W = 1,
            //Select reset strategy.
            // "MINI" for resetting minimally required FFs
            // "NONE" for relying on FFs having a defined value on startup
            parameter reset_strategy="MINI",
        
            //Number of CSR registers. These are allocated after the normal
            // GPR registers in the RAM.
            parameter csr_regs=4,
        
            //Internal parameters calculated from above values. Do not change
            parameter B=W-1,
            parameter raw=$clog2(32+csr_regs), //Register address width
            parameter l2w=$clog2(width), //log2 of width
            parameter aw=5+raw-l2w) //Address width
          (
           //SERV side
 200008    input wire		   i_clk,
%000002    input wire		   i_rst,
 001734    input wire		   i_wreq,
 003476    input wire		   i_rreq,
 005210    output wire		   o_ready,
%000000    input wire [raw-1:0]	   i_wreg0,
%000001    input wire [raw-1:0]	   i_wreg1,
 001741    input wire		   i_wen0,
%000000    input wire		   i_wen1,
 004058    input wire [B:0]	   i_wdata0,
 000868    input wire [B:0]	   i_wdata1,
%000000    input wire [raw-1:0]	   i_rreg0,
%000000    input wire [raw-1:0]	   i_rreg1,
 002462    output wire [B:0]	   o_rdata0,
 000146    output wire [B:0]	   o_rdata1,
           //RAM side
 008976    output wire [aw-1:0]	   o_waddr,
 007106    output wire [width-1:0] o_wdata,
 027854    output wire		   o_wen,
%000000    output wire [aw-1:0]	   o_raddr,
 003475    output wire		   o_ren,
 002610    input wire [width-1:0]  i_rdata);
        
           localparam ratio = width/W;
           localparam CMSB = 4-$clog2(W); //Counter MSB
           localparam l2r  = $clog2(ratio);
        
 003476    reg 				   rgnt;
           assign o_ready = rgnt | i_wreq;
 005209    reg [CMSB:0] 	  rcnt;
        
 098116    reg 		  rtrig1;
           /*
            ********** Write side ***********
            */
        
 008976    wire [CMSB:0] 	     wcnt;
        
 004058    reg [width-1:0]   wdata0_r;
 000868    reg [width+W-1:0]   wdata1_r;
        
 001741    reg 		     wen0_r;
%000000    reg 		     wen1_r;
 098116    wire 	     wtrig0;
 098117    wire 	     wtrig1;
        
           assign wtrig0 = rtrig1;
        
           generate if (ratio == 2) begin : gen_wtrig_ratio_eq_2
              assign wtrig1 =  wcnt[0];
           end else begin : gen_wtrig_ratio_neq_2
              reg wtrig0_r;
              always @(posedge i_clk) wtrig0_r <= wtrig0;
              assign wtrig1 = wtrig0_r;
           end
           endgenerate
        
           assign 	     o_wdata = wtrig1 ?
        			       wdata1_r[width-1:0] :
        			       wdata0_r;
        
 042772    wire [raw-1:0] wreg  = wtrig1 ? i_wreg1 : i_wreg0;
           generate if (width == 32) begin : gen_w_eq_32
              assign o_waddr = wreg;
           end else begin : gen_w_neq_32
              assign o_waddr = {wreg, wcnt[CMSB:l2r]};
           end
           endgenerate
        
           assign o_wen = (wtrig0 & wen0_r) | (wtrig1 & wen1_r);
        
           assign wcnt = rcnt-4;
        
 100003    always @(posedge i_clk) begin
 049058       if (wcnt[0]) begin
 049058 	 wen0_r    <= i_wen0;
 049058 	 wen1_r    <= i_wen1;
              end
        
 100003       wdata0_r  <= {i_wdata0,wdata0_r[width-1:W]};
 100003       wdata1_r  <= {i_wdata1,wdata1_r[width+W-1:W]};
        
           end
        
           /*
            ********** Read side ***********
            */
        
        
 098117    wire 	  rtrig0;
        
%000000    wire [raw-1:0] rreg = rtrig0 ? i_rreg1 : i_rreg0;
           generate if (width == 32) begin : gen_rreg_eq_32
              assign o_raddr = rreg;
           end else begin : gen_rreg_neq_32
              assign o_raddr = {rreg, rcnt[CMSB:l2r]};
           end
           endgenerate
        
 002462    reg [width-1:0]  rdata0;
%000000    reg [width-1-W:0]  rdata1;
        
 003475    reg 		    rgate;
        
           assign o_rdata0 = rdata0[B:0];
           assign o_rdata1 = rtrig1 ? i_rdata[B:0] : rdata1[B:0];
        
           assign rtrig0 = (rcnt[l2r-1:0] == 1);
        
           generate if (ratio == 2) begin : gen_ren_w_eq_2
              assign o_ren = rgate;
           end else begin : gen_ren_w_neq_2
              assign o_ren = rgate & (rcnt[l2r-1:1] == 0);
           end
           endgenerate
        
 003476    reg 	      rreq_r;
        
           generate if (ratio > 2) begin : gen_rdata1_w_neq_2
              always @(posedge i_clk) begin
        	 rdata1 <= {{W{1'b0}},rdata1[width-W-1:W]};
        	 if (rtrig1)
        	   rdata1[width-W-1:0] <= i_rdata[width-1:W];
              end
           end else begin : gen_rdata1_w_eq_2
 049058       always @(posedge i_clk) if (rtrig1) rdata1 <= i_rdata[W*2-1:W];
           end
           endgenerate
        
 100003    always @(posedge i_clk) begin
 004342       if (&rcnt | i_rreq)
 004342 	rgate <= i_rreq;
        
 100003       rtrig1 <= rtrig0;
 100003       rcnt <= rcnt+{{CMSB{1'b0}},1'b1};
 002605       if (i_rreq | i_wreq)
 002605 	 rcnt <= {{CMSB-1{1'b0}},i_wreq,1'b0};
        
 100003       rreq_r <= i_rreq;
 100003       rgnt <= rreq_r;
        
 100003       rdata0 <= {{W{1'b0}}, rdata0[width-1:W]};
 049058       if (rtrig0)
 049058 	rdata0 <= i_rdata;
        
%000003       if (i_rst) begin
%000000 	 if (reset_strategy != "NONE") begin
%000003 	    rgate <= 1'b0;
%000003 	    rgnt <= 1'b0;
%000003 	    rreq_r <= 1'b0;
%000003 	    rcnt <= {CMSB+1{1'b0}};
        	 end
              end
           end
        
        
        
        endmodule
        
