module TopModule (
  input  clk,
  input  a,
  input  b,
  output q,
  output reg state
);

  // One-bit memory behaves as a full-adder carry; q is the sum bit.
  // next state = majority(a, b, state); q = a ^ b ^ state
  always @(posedge clk) begin
    state <= (a & b) | (state & (a | b));
  end

  assign q = a ^ b ^ state;

endmodule
