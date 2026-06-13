module TopModule (
  input clock,
  input a,
  output reg p,
  output reg q
);
  // p: high-level transparent latch of a (follows a while clock=1, holds when clock=0)
  always_latch begin
    if (clock)
      p = a;
  end

  // q: samples p on the falling edge of clock
  always @(negedge clock) begin
    q <= p;
  end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
