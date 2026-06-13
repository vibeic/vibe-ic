module TopModule (
  input  clk,
  input  a,
  output q
);

  // From waveform: q(n) = ~a(n-1) -- a D flip-flop capturing the inverted input.
  reg q_reg;

  always @(posedge clk)
    q_reg <= ~a;

  assign q = q_reg;


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q_reg = 0;
  end

endmodule
