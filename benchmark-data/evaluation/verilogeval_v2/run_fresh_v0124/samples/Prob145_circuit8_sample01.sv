module TopModule (
    input  clock,
    input  a,
    output reg p,
    output reg q
);
    // p: transparent latch, follows a while clock is high, holds when low.
    always_latch begin
        if (clock) p = a;
    end

    // q: negative-edge-triggered flip-flop that samples p.
    always @(negedge clock) begin
        q <= p;
    end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
