// Auto-generated unit TB for case=single_block_nist_appa_abcdbcde_mnopqr
// kind=functional_vector polarity=positive
// stimulus: 448-bit message,padded
// expected: 248d6a61 d20638b8 e5c02693 0c3e6039 a33ce459 64ff2167 f6ecedd4 19db06c1
`timescale 1ns/1ps
module single_block_nist_appa_abcdbcde_mnopqr;
  reg clk = 0;
  reg reset_n = 0;
  initial begin
    $display("[TB single_block_nist_appa_abcdbcde_mnopqr] BEGIN — opcode=0x00 kind=functional_vector");
    #100 reset_n = 1;
    #1000 $display("[TB single_block_nist_appa_abcdbcde_mnopqr] PASS_PLACEHOLDER (replace with real stimulus)");
    $finish;
  end
  always #5 clk = ~clk;
  // sha256 u_dut (.clk(clk), .reset_n(reset_n), ...);
endmodule
