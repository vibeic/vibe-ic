// Prob062_bugs_mux2 — 8-bit 2:1 mux. sel=1 -> a, sel=0 -> b.
module TopModule (
  input sel,
  input [7:0] a,
  input [7:0] b,
  output reg [7:0] out
);

  always @(*)
    out = sel ? a : b;

endmodule
