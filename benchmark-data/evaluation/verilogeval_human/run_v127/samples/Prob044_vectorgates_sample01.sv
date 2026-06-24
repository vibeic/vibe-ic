module TopModule (
  input [2:0] a,
  input [2:0] b,
  output [2:0] out_or_bitwise,
  output out_or_logical,
  output [5:0] out_not
);

  assign out_or_bitwise = a | b;
  assign out_or_logical = a || b;
  // Inverse of b in upper half [5:3], inverse of a in lower half [2:0].
  assign out_not = {~b, ~a};

endmodule
