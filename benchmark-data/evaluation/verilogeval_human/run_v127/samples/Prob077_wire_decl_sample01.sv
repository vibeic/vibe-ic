module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out,
  output out_n
);

  wire and_ab;
  wire and_cd;

  assign and_ab = a & b;       // first AND gate
  assign and_cd = c & d;       // second AND gate
  assign out    = and_ab | and_cd;  // OR layer
  assign out_n  = ~out;        // inverted output

endmodule
