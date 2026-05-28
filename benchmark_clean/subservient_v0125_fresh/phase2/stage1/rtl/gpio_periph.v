// SPDX-License-Identifier: Apache-2.0
// Author: Vibe-IC Plugin catalog-glue-author skill  (GENERATED glue)
//
// gpio_periph — 1-bit write-only memory-mapped GPIO peripheral.
//
// This module is AI-authored from the L1-L9 spec (NOT a reused IP):
//   - L2: "GPIO peripheral ... can act as a simple output debug bit or
//          UART tx (firmware bit-banged)".
//   - L3: o_gpio >= 1-bit output.
//   - L4 (N/A) + L5 (N/A): no chip register — GPIO is a firmware-defined
//          memory mapping. By convention (Plugin choice, R3-permitted)
//          the GPIO mailbox is the highest byte address in the shared
//          SRAM window (MEMSIZE-1); a firmware store to that byte echoes
//          wdata[0] onto o_gpio.
//
// It snoops the shared data-memory write bus (8-bit byte writes that the
// servile WB->SRAM bridge issues), so no extra address decoder is needed
// at the chip top.
// -----------------------------------------------------------------------------
`default_nettype none

module gpio_periph
  #(parameter MEMSIZE = 1024,
    parameter ADDR_W  = 10)
   (input  wire              i_clk,
    input  wire              i_rst,        // synchronous active-high
    input  wire [ADDR_W-1:0] i_addr,       // byte address of the write
    input  wire [7:0]        i_wdata,      // write data byte
    input  wire              i_we,         // write enable
    input  wire              i_cyc,        // bus cycle valid
    output reg               o_gpio);

   localparam [ADDR_W-1:0] GPIO_MAILBOX = MEMSIZE - 1;

   // Power-up initializer — sample at t=0 sees 0 not X (Verilator-clean).
   initial o_gpio = 1'b0;

   always @(posedge i_clk) begin
      if (i_rst)
         o_gpio <= 1'b0;
      else if (i_cyc & i_we & (i_addr == GPIO_MAILBOX))
         o_gpio <= i_wdata[0];
   end

endmodule

`default_nettype wire
