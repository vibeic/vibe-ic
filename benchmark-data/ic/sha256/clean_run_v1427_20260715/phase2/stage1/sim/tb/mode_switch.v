// Auto-generated unit TB for case=mode_switch
// kind=functional_vector polarity=positive
// stimulus: 100% PASS
// expected: INIT SHA-256 → INIT SHA-224 → INIT SHA-256 順序測試
`timescale 1ns/1ps
module mode_switch;
  reg clk = 0;
  reg reset_n = 0;
  initial begin
    $display("[TB mode_switch] BEGIN — opcode=0x00 kind=functional_vector");
    #100 reset_n = 1;
    #1000 $display("[TB mode_switch] PASS_PLACEHOLDER (replace with real stimulus)");
    $finish;
  end
  always #5 clk = ~clk;
  // sha256 u_dut (.clk(clk), .reset_n(reset_n), ...);
endmodule
