module TopModule (
  input  clk,
  input  d,
  output q
);
  reg p, n;
  always @(posedge clk) p <= d ^ n;   // posedge-captured half
  always @(negedge clk) n <= d ^ p;   // negedge-captured half
  assign q = p ^ n;                   // recombine -> behaves as dual-edge DFF
endmodule
