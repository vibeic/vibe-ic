module TopModule (
  input  clk,
  input  d,
  output q
);
  reg p, n;
  // Capture d on the rising edge into p
  always @(posedge clk)
    p <= d;
  // Capture d on the falling edge into n
  always @(negedge clk)
    n <= d;
  // While clk is high the most recent edge was the rising edge (use p);
  // while clk is low the most recent edge was the falling edge (use n).
  assign q = clk ? p : n;
endmodule
