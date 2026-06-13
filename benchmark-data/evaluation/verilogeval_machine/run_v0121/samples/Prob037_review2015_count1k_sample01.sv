// 10-bit counter 0..999. Synchronous reset to 0; wraps 999 -> 0.
module TopModule (
  input clk,
  input reset,
  output reg [9:0] q
);

  initial q = 10'd0;

  always @(posedge clk) begin
    if (reset)
      q <= 10'd0;
    else if (q == 10'd999)
      q <= 10'd0;
    else
      q <= q + 10'd1;
  end

endmodule
