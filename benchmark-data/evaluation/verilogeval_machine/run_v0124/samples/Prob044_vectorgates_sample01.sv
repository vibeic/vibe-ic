module TopModule (
  input [2:0] a,
  input [2:0] b,
  output [2:0] out_or_bitwise,
  output out_or_logical,
  output [5:0] out_not
);
  assign out_or_bitwise = a | b;
  assign out_or_logical = a || b;
  // Bitwise NOT of both inputs; b in upper bits, a in lower bits.
  assign out_not = {~b, ~a};
endmodule
