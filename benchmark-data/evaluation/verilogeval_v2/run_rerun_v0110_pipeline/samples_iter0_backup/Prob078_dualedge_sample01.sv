module TopModule (
  input  clk,
  input  d,
  output q
);
  reg p, n;
  always @(posedge clk) p <= d ^ n;
  always @(negedge clk) n <= d ^ p;
  assign q = p ^ n;
endmodule
