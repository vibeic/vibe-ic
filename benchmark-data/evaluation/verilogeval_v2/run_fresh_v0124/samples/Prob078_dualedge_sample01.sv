module TopModule (
    input  clk,
    input  d,
    output q
);
    reg p, n;
    always @(posedge clk) p <= d;
    always @(negedge clk) n <= d;
    // When clk is high, the most recent capture was on the rising edge (p);
    // when clk is low, the most recent capture was on the falling edge (n).
    assign q = clk ? p : n;

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    p = 0;
    n = 0;
  end

endmodule
