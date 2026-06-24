module TopModule (
  input clk,
  input areset,
  input [7:0] d,
  output reg [7:0] q
);

  always @(posedge clk, posedge areset)
    if (areset)
      q <= 8'b0;
    else
      q <= d;

endmodule
