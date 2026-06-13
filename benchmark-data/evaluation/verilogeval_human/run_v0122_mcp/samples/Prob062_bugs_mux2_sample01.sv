// 8-bit wide 2-to-1 mux (bug fixed: full 8-bit output and select).
// sel=0 -> a, sel=1 -> b.
module TopModule (
  input sel,
  input [7:0] a,
  input [7:0] b,
  output reg [7:0] out
);

  always @(*)
    out = sel ? b : a;

endmodule
