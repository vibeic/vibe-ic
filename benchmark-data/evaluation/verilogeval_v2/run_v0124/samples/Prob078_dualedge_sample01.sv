module TopModule (
  input  clk,
  input  d,
  output q
);
  reg p, n;

  always @(posedge clk)
    p <= d;

  always @(negedge clk)
    n <= d;

  assign q = clk ? p : n;

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    p = 0;
    n = 0;
  end

endmodule
