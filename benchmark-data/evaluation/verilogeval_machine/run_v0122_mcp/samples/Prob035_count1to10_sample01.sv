// Prob035_count1to10 — counter cycling 1..10 then back to 1.
// Synchronous reset (checked inside posedge-clk block) forces q to 1.
module TopModule (
  input clk,
  input reset,
  output reg [3:0] q
);

  always @(posedge clk) begin
    if (reset)
      q <= 4'd1;
    else if (q == 4'd10)
      q <= 4'd1;
    else
      q <= q + 4'd1;
  end

endmodule
