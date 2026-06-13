// Counter cycling 1..10. Synchronous reset sets q to 1; wraps 10 -> 1.
module TopModule (
  input clk,
  input reset,
  output reg [3:0] q
);

  initial q = 4'd1;

  always @(posedge clk) begin
    if (reset)
      q <= 4'd1;
    else if (q == 4'd10)
      q <= 4'd1;
    else
      q <= q + 4'd1;
  end

endmodule
