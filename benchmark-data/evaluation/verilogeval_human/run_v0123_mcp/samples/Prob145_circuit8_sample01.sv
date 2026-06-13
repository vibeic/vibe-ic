module TopModule (
  input clock,
  input a,
  output reg p,
  output reg q
);

  // p: positive-level transparent latch of a (follows a while clock is high)
  always_latch begin
    if (clock)
      p = a;
  end

  // q: negative-edge triggered flip-flop capturing p
  always @(negedge clock) begin
    q <= p;
  end

endmodule
