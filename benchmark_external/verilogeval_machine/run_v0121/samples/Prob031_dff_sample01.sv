// D flip-flop: q <= d on rising edge of clk. No reset.
module TopModule (
  input clk,
  input d,
  output reg q
);

  always @(posedge clk)
    q <= d;

endmodule
