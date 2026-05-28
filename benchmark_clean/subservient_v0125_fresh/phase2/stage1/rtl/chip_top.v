// SPDX-License-Identifier: Apache-2.0
// Author: Vibe-IC Plugin close-loop sub-agent (GENERATED chip-top wrapper)
//
// chip_top — Thin wrapper around `subservient` so that L9.top_module
// ("chip_top") matches the actual synthesised top, while the
// catalog-glue-author-emitted SoC keeps its natural name `subservient`.
//
// This wrapper exists solely to bridge the L9 top-name contract.
// It performs no logic transformation; the port list mirrors `subservient`
// 1:1 with identical widths, polarities, and defaults.
//
// L9 / L3 contract preserved:
//   - i_clk          : 1-bit clock
//   - i_rst          : 1-bit synchronous active-high reset
//   - o_sram_addr    : 10-bit external SRAM byte address
//   - o_sram_wdata   : 8-bit external SRAM write data
//   - i_sram_rdata   : 8-bit external SRAM read data
//   - o_sram_we      : external SRAM write-enable
//   - o_sram_cyc     : external SRAM cycle-valid
//   - o_gpio         : 1-bit GPIO output
// Parameters mirror subservient defaults (L1/L3): MEMSIZE=1024,
// RESET_PC=32'h00000000, WITH_CSR=1.
// -----------------------------------------------------------------------------
`default_nettype none

module chip_top
  #(parameter MEMSIZE  = 1024,
    parameter RESET_PC = 32'h00000000,
    parameter WITH_CSR = 1)
   (input  wire        i_clk,
    input  wire        i_rst,

    output wire [9:0]  o_sram_addr,
    output wire [7:0]  o_sram_wdata,
    input  wire [7:0]  i_sram_rdata,
    output wire        o_sram_we,
    output wire        o_sram_cyc,

    output wire        o_gpio);

   subservient
     #(.MEMSIZE  (MEMSIZE),
       .RESET_PC (RESET_PC),
       .WITH_CSR (WITH_CSR))
   u_subservient
     (.i_clk        (i_clk),
      .i_rst        (i_rst),
      .o_sram_addr  (o_sram_addr),
      .o_sram_wdata (o_sram_wdata),
      .i_sram_rdata (i_sram_rdata),
      .o_sram_we    (o_sram_we),
      .o_sram_cyc   (o_sram_cyc),
      .o_gpio       (o_gpio));

endmodule

`default_nettype wire
