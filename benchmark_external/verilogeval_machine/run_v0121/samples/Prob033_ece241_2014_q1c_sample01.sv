// 8-bit signed adder with overflow detection.
// s = a + b; overflow when both operands same sign but result differs.
module TopModule (
  input [7:0] a,
  input [7:0] b,
  output [7:0] s,
  output overflow
);

  assign s = a + b;
  assign overflow = (a[7] == b[7]) && (s[7] != a[7]);

endmodule
