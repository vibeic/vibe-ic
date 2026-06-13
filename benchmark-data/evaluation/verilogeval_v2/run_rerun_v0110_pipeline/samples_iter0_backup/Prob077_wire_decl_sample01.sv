module TopModule (
  input  a,
  input  b,
  input  c,
  input  d,
  output out,
  output out_n
);
  wire ab = a & b;
  wire cd = c & d;
  assign out   = ab | cd;
  assign out_n = ~out;
endmodule
