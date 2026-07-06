module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out,
  output out_n
);

  // First layer: two AND gates.
  wire and_ab;
  wire and_cd;
  assign and_ab = a & b;
  assign and_cd = c & d;

  // Second layer: OR the two AND outputs, plus an inverted copy.
  assign out   = and_ab | and_cd;
  assign out_n = ~out;

endmodule
