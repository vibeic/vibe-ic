// 8 negedge-triggered DFFs with active-high SYNCHRONOUS reset to 0x34.
module TopModule (
  input clk,
  input [7:0] d,
  input reset,
  output reg [7:0] q
);

  always @(negedge clk) begin
    if (reset)
      q <= 8'h34;
    else
      q <= d;
  end

endmodule
