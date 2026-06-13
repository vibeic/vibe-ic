// Bitwise-OR, logical-OR and NOT of two 3-bit vectors.
// out_not: [5:3] = ~b, [2:0] = ~a.
module TopModule (
  input [2:0] a,
  input [2:0] b,
  output [2:0] out_or_bitwise,
  output out_or_logical,
  output [5:0] out_not
);

  assign out_or_bitwise = a | b;
  assign out_or_logical = a || b;
  assign out_not = {~b, ~a};

endmodule
