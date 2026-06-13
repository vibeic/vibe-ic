module TopModule (
  input sel,
  input [7:0] a,
  input [7:0] b,
  output reg [7:0] out
);
  always @(*)
    out = sel ? a : b;   // sel=0 -> b, sel=1 -> a
endmodule
