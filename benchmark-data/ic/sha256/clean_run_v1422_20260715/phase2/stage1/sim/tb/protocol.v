// Auto-generated unit TB for case=protocol
// kind=functional_vector polarity=positive
// stimulus: 100% PASS
// expected: INIT during BUSY / NEXT without prior INIT / read DIGEST during BUSY / write BLOCK during BUSY
`timescale 1ns/1ps
module protocol;
  reg clk = 0;
  reg reset_n = 0;
  initial begin
    $display("[TB protocol] BEGIN — opcode=0x00 kind=functional_vector");
    #100 reset_n = 1;
    #1000 $display("[TB protocol] PASS_PLACEHOLDER (replace with real stimulus)");
    $finish;
  end
  always #5 clk = ~clk;
  // sha256 u_dut (.clk(clk), .reset_n(reset_n), ...);
endmodule
