// fakeram45_2048x39 — behavioral model for simulation (matches the FakeRAM45
// abstract macro pin list: single-port synchronous SRAM, 1-cycle read latency,
// active-high ce/we, bitwise write mask). NOT a real memory compiler output —
// FreePDK45/Nangate45 is a non-foundry enablement; this macro is abstract.
module fakeram45_2048x39 (rd_out, addr_in, we_in, wd_in, w_mask_in, clk, ce_in);
   parameter BITS = 39;
   parameter WORD_DEPTH = 2048;
   parameter ADDR_WIDTH = 11;
   output reg [BITS-1:0]   rd_out;
   input  [ADDR_WIDTH-1:0] addr_in;
   input                   we_in;
   input  [BITS-1:0]       wd_in;
   input  [BITS-1:0]       w_mask_in;
   input                   clk;
   input                   ce_in;
   reg [BITS-1:0] mem [0:WORD_DEPTH-1];
   always @(posedge clk) begin
      if (ce_in) begin
         if (we_in)
            mem[addr_in] <= (wd_in & w_mask_in) | (mem[addr_in] & ~w_mask_in);
         else
            rd_out <= mem[addr_in];
      end
   end
endmodule
