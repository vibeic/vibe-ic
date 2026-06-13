module TopModule (
  input  clock,
  input  a,
  output p,
  output q
);

  reg p_r;
  reg q_r;

  // p is a positive level-sensitive latch of a (transparent while clock high)
  always @(*) begin
    if (clock)
      p_r = a;
  end

  // q captures p on the falling edge of the clock
  always @(negedge clock) begin
    q_r <= p_r;
  end

  assign p = p_r;
  assign q = q_r;

endmodule
