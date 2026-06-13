// Prob074_ece241_2014_q4 — 3-bit state machine, z = NOR of state bits.
// s[2] <= x ^ s[2];  s[1] <= x & ~s[1];  s[0] <= x | ~s[0]
// z = ~(|s).  Reset-less: power-up s=0 via initial block.
module TopModule (
  input clk,
  input x,
  output z
);

  reg [2:0] s;
  initial s = 3'b0;

  always @(posedge clk) begin
    s[2] <= x ^ s[2];
    s[1] <= x & ~s[1];
    s[0] <= x | ~s[0];
  end

  assign z = ~(s[2] | s[1] | s[0]);

endmodule
