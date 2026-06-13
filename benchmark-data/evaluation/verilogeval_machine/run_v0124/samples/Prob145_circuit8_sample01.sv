module TopModule (
  input clock,
  input a,
  output reg p,
  output reg q
);
  always @(negedge clock) begin
    q <= a;
  end

  always_latch begin
    if (clock) p = a;
  end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
