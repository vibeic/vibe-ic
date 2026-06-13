module TopModule (
  input [4:1] x,
  output logic f
);
  // Minimal SOP from K-map (no don't-cares):
  // f = ~x1&x3 | ~x2&~x4 | x2&x3&x4
  assign f = (~x[1] & x[3]) | (~x[2] & ~x[4]) | (x[2] & x[3] & x[4]);
endmodule
