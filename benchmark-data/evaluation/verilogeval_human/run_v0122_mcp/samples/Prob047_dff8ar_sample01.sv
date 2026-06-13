// 8 posedge-triggered DFFs with active-high ASYNCHRONOUS reset to 0.
module TopModule (
  input clk,
  input [7:0] d,
  input areset,
  output reg [7:0] q
);

  always @(posedge clk or posedge areset) begin
    if (areset)
      q <= 8'h00;
    else
      q <= d;
  end

endmodule
