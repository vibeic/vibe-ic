// Auto-generated unit TB for case=tc1_reset
// kind=functional_vector polarity=positive
// stimulus: reset 行為
// expected: busy=0、done=0,host 存取立即可用
`timescale 1ns/1ps
module tc1_reset;
  reg clk = 0;
  reg reset_n = 0;
  initial begin
    $display("[TB tc1_reset] BEGIN — opcode=0x00 kind=functional_vector");
    #100 reset_n = 1;
    #1000 $display("[TB tc1_reset] PASS_PLACEHOLDER (replace with real stimulus)");
    $finish;
  end
  always #5 clk = ~clk;
  // edge_llm_accel u_dut (.clk(clk), .reset_n(reset_n), ...);
endmodule
