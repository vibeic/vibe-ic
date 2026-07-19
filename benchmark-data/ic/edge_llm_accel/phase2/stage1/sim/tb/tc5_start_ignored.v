// Auto-generated unit TB for case=tc5_start_ignored
// kind=functional_vector polarity=positive
// stimulus: busy 中 start 忽略
// expected: 整個 run 僅一次 done;第二個 start 不重啟、不排隊(L4 §4.3)
`timescale 1ns/1ps
module tc5_start_ignored;
  reg clk = 0;
  reg reset_n = 0;
  initial begin
    $display("[TB tc5_start_ignored] BEGIN — opcode=0x00 kind=functional_vector");
    #100 reset_n = 1;
    #1000 $display("[TB tc5_start_ignored] PASS_PLACEHOLDER (replace with real stimulus)");
    $finish;
  end
  always #5 clk = ~clk;
  // edge_llm_accel u_dut (.clk(clk), .reset_n(reset_n), ...);
endmodule
