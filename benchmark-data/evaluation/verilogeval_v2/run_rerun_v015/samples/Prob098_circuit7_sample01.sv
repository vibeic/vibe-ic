module TopModule (
  input  clk,
  input  a,
  output q
);

  // From the waveform, q is the registered inverse of a:
  // at each posedge, q <= ~a (value of a sampled before the edge).
  reg q_reg;

  always @(posedge clk)
    q_reg <= ~a;

  assign q = q_reg;

endmodule
