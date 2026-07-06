module TopModule (
  input clk,
  input reset,
  input [7:0] d,
  output reg [7:0] q
);

  always @(posedge clk)
    if (reset)
      q <= 8'b0;
    else
      q <= d;

endmodule
