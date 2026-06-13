// Serial 2's complementer, LSB first.
// Copy bits up to and including the first 1, then invert the rest.
// 'seen' latches once x has been 1. Output z = seen ? ~x : x.
// Async positive-edge active-high reset clears 'seen'.
module TopModule (
  input clk,
  input areset,
  input x,
  output z
);

  reg seen;

  always @(posedge clk or posedge areset) begin
    if (areset)
      seen <= 1'b0;
    else if (x)
      seen <= 1'b1;
  end

  assign z = seen ? ~x : x;

endmodule
