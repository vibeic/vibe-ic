// Prob067_countslow — 4-bit decade counter with slow enable.
// Reset checked inside posedge-clk-only block => synchronous (structure beats adjective).
// Increment only when slowena high; wrap 9->0.
module TopModule (
  input clk,
  input slowena,
  input reset,
  output reg [3:0] q
);

  always @(posedge clk) begin
    if (reset)
      q <= 4'd0;
    else if (slowena) begin
      if (q == 4'd9)
        q <= 4'd0;
      else
        q <= q + 4'd1;
    end
    // slowena low: hold
  end

endmodule
