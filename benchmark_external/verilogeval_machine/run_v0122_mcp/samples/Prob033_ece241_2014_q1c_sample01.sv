// Prob033_ece241_2014_q1c — 8-bit signed adder with overflow flag.
// s = a + b (lower 8 bits). Signed overflow: operands same sign, result
// differs in sign.
module TopModule (
  input [7:0] a,
  input [7:0] b,
  output [7:0] s,
  output overflow
);

  wire [7:0] sum = a + b;
  assign s = sum;
  assign overflow = (a[7] == b[7]) && (sum[7] != a[7]);

endmodule
