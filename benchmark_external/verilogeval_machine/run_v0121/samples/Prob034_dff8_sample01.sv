// 8-bit register: q <= d on rising edge of clk. Power-up default 8'h0.
module TopModule (
  input clk,
  input [7:0] d,
  output reg [7:0] q
);

  initial q = 8'h0;

  always @(posedge clk)
    q <= d;

endmodule
