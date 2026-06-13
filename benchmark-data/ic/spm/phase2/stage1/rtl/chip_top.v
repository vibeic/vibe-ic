// SPDX-License-Identifier: Apache-2.0
// v0.1.62 auto-emitted chip_top wrapper (phase2_one_shot_runner).
// L9.top_module = 'chip_top' but rtl/ only defined 'spm'
// (in spm.v). This thin pass-through lets yosys synth
// against L9's expected top without modifying the authored RTL.
`default_nettype none
module chip_top #(
    parameter size = 32
) (
    input  wire             clk,
    input  wire             rst,                              
    input  wire [size-1:0]  x,                             
    input  wire             y,                                     
    output reg              p                                     
);
  spm #(.size(size)) u_dut (
    .clk(clk),
    .rst(rst),
    .x(x),
    .y(y),
    .p(p)
  );
endmodule
`default_nettype wire
