module TopModule (
  input [4:1] x,
  output logic f
);

  // Cover chosen from K-map (don't-cares assigned for a simple expression):
  // f = (~x1 & x3) | (x1 & x2 & ~x3 & x4)
  assign f = (~x[1] & x[3]) | (x[1] & x[2] & ~x[3] & x[4]);

endmodule
