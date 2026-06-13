// SPDX-License-Identifier: Apache-2.0
// v0.1.62 auto-emitted chip_top wrapper (phase2_one_shot_runner).
// L9.top_module = 'chip_top' but rtl/ only defined 'sha256'
// (in sha256.v). This thin pass-through lets yosys synth
// against L9's expected top without modifying the authored RTL.
`default_nettype none
module chip_top (
    input  wire        clk,
    input  wire        reset_n,                                  
    input  wire        cs,                           
    input  wire        we,                              
    input  wire [7:0]  address,
    input  wire [31:0] write_data,
    output reg  [31:0] read_data,
    output reg         error
);
  sha256 u_dut (
    .clk(clk),
    .reset_n(reset_n),
    .cs(cs),
    .we(we),
    .address(address),
    .write_data(write_data),
    .read_data(read_data),
    .error(error)
  );
endmodule
`default_nettype wire
