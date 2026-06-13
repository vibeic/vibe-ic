module TopModule (
  input  clk,
  input  d,
  output q
);

  reg p;  // captured on posedge
  reg n;  // captured on negedge

  always @(posedge clk)
    p <= d;

  always @(negedge clk)
    n <= d;

  assign q = clk ? p : n;

endmodule
