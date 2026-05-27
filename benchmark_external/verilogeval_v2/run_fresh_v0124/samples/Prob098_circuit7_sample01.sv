module TopModule (
  input  clk,
  input  a,
  output q
);
  // From the waveform: on each posedge, q takes the inverse of a.
  // a=0 -> q becomes 1; a=1 -> q becomes 0.
  reg q_reg;
  assign q = q_reg;

  always @(posedge clk) begin
    q_reg <= ~a;
  end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q_reg = 0;
  end

endmodule
