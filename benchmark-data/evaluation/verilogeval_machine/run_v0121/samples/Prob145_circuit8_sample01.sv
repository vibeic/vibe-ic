module TopModule (
  input clock,
  input a,
  output reg p = 1'b0,
  output reg q = 1'b0
);
  // q: captured on the falling edge of clock
  always @(negedge clock)
    q <= a;

  // p: re-captures a on any change of a, only while clock is high
  always @(a)
    if (clock)
      p <= a;
endmodule
