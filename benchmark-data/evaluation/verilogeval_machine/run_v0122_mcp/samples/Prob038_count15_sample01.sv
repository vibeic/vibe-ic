// Prob038_count15 — 4-bit counter, synchronous reset to 0, wraps 15->0.
module TopModule (
  input clk,
  input reset,
  output reg [3:0] q
);

  always @(posedge clk) begin
    if (reset)
      q <= 4'd0;
    else
      q <= q + 4'd1;
  end

endmodule
