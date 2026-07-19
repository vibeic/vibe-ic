// Auto-generated unit TB for case=tc4_run_protocol
// kind=functional_vector polarity=positive
// stimulus: compute run 協定
// expected: busy 於 1 cycle 內升起;done 恰 pulse 一次(≤4096 cycles);busy 同步降回 0
`timescale 1ns/1ps
module tc4_run_protocol;
  reg clk = 0;
  reg reset_n = 0;
  initial begin
    $display("[TB tc4_run_protocol] BEGIN — opcode=0x00 kind=functional_vector");
    #100 reset_n = 1;
    #1000 $display("[TB tc4_run_protocol] PASS_PLACEHOLDER (replace with real stimulus)");
    $finish;
  end
  always #5 clk = ~clk;
  // edge_llm_accel u_dut (.clk(clk), .reset_n(reset_n), ...);
endmodule
