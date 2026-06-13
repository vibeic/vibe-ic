//      // verilator_coverage annotation
        /*
         * serv_rf_ram.v : SRAM-based RF storage for SERV
         *
         * SPDX-FileCopyrightText: 2019 Olof Kindgren <olof@award-winning.me>
         * SPDX-License-Identifier: ISC
         */
        module serv_rf_ram
          #(parameter width=0,
            parameter csr_regs=4,
            parameter depth=32*(32+csr_regs)/width)
 200008    (input wire i_clk,
 008976     input wire [$clog2(depth)-1:0] i_waddr,
 007106     input wire [width-1:0] 	   i_wdata,
 027854     input wire 			   i_wen,
%000000     input wire [$clog2(depth)-1:0] i_raddr,
 003475     input wire			   i_ren,
 002610     output wire [width-1:0] 	   o_rdata);
        
           reg [width-1:0] 		   memory [0:depth-1];
 002610    reg [width-1:0] 		   rdata ;
        
 100003    always @(posedge i_clk) begin
 013927       if (i_wen)
 013927 	memory[i_waddr] <= i_wdata;
 100003       rdata <= i_ren ? memory[i_raddr] : {width{1'bx}};
           end
        
           /* Reads from reg x0 needs to return 0
            Check that the part of the read address corresponding to the register
            is zero and gate the output
            width LSB of reg index $clog2(width)
            2     4                1
            4     3                2
            8     2                3
            16    1                4
            32    0                5
            */
 048012    reg regzero;
        
 100003    always @(posedge i_clk)
 100003      regzero <= !(|i_raddr[$clog2(depth)-1:5-$clog2(width)]);
        
           assign o_rdata = rdata & ~{width{regzero}};
        
        `ifdef SERV_CLEAR_RAM
           integer i;
           initial
             for (i=0;i<depth;i=i+1)
               memory[i] = {width{1'd0}};
        `endif
        endmodule
        
