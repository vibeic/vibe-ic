module TopModule (
  input  clk,
  input  a,
  output q
);
  // From waveform: positive-edge D flip-flop with q <= ~a.
  reg q_reg;
  always @(posedge clk)
    q_reg <= ~a;
  assign q = q_reg;
endmodule
