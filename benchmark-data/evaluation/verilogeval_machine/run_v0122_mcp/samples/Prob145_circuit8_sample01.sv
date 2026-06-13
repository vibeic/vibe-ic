// Prob145_circuit8 — negedge DFF q<=a; clock-high transparent latch p=a.
module TopModule (
  input clock,
  input a,
  output reg p,
  output reg q
);

  initial q = 1'b0;   // reset-less registered output power-up (separate block)

  always @(negedge clock)
    q <= a;

  always_latch
    if (clock)
      p = a;

endmodule
