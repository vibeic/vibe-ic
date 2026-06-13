module TopModule (
  input [4:1] x,
  output logic f
);

  // Don't-cares chosen to give: f = (~x1 & x3) | (x2 & ~x3 & x4)
  assign f = (~x[1] & x[3]) | (x[2] & ~x[3] & x[4]);

endmodule
