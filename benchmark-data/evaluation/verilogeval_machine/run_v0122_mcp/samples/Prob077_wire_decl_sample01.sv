// Prob077_wire_decl — AOI: out = (a&b) | (c&d); out_n = ~out.
module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out,
  output out_n
);

  wire w1, w2;
  assign w1 = a & b;
  assign w2 = c & d;
  assign out   = w1 | w2;
  assign out_n = ~out;

endmodule
