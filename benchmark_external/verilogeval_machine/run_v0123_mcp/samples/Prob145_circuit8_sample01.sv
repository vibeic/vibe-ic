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
endmodule
