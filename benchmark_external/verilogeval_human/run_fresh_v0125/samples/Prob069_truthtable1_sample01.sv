module TopModule (
  input x3,
  input x2,
  input x1,
  output f
);

  // f=1 for x3x2x1 = 010,011,101,111
  // = x2 (when x3=0) OR x1 (when x3=1) => (~x3 & x2) | (x3 & x1)
  assign f = (~x3 & x2) | (x3 & x1);

endmodule
