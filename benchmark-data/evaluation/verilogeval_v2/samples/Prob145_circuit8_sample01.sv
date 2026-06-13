module TopModule (
  input  clock,
  input  a,
  output reg p,
  output reg q
);

  // p: positive level-sensitive latch of a (transparent when clock is high)
  always @(*) begin
    if (clock) p = a;
  end

  // q: negative level-sensitive latch of p (transparent when clock is low)
  always @(*) begin
    if (!clock) q = p;
  end

endmodule
