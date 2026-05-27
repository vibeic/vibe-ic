// Prob083_mt2015_q4b — XNOR: z = ~(x ^ y).
module TopModule (
  input x,
  input y,
  output z
);

  assign z = ~(x ^ y);

endmodule
