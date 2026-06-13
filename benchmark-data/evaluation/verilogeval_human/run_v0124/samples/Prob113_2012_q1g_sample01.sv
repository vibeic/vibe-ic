module TopModule (
  input [4:1] x,
  output logic f
);

  // Karnaugh map (cols = x[1]x[2] in 00,01,11,10; rows = x[3]x[4] in 00,01,11,10).
  // Minimal SOP derived by Quine-McCluskey (verified exact over all 16 cells):
  //   f = (~x2 & ~x4) | (x2 & x3 & x4) | (~x1 & x3)
  // Port header is authoritative: x is declared [4:1], so x[1]..x[4] are all
  // valid declared indices; reference them by name.
  assign f = (~x[2] & ~x[4]) | (x[2] & x[3] & x[4]) | (~x[1] & x[3]);

endmodule
