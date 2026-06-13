// 8-bit positive-edge detector. pedge[i] set the cycle after in[i] goes
// 0->1. Register previous value, AND new value with inverted previous.
module TopModule (
  input clk,
  input [7:0] in,
  output reg [7:0] pedge
);

  reg [7:0] in_prev;

  // Reset-less registered outputs: power-up initializers for determinism.
  initial begin
    pedge   = 8'b0;
    in_prev = 8'b0;
  end

  always @(posedge clk) begin
    pedge   <= ~in_prev & in;
    in_prev <= in;
  end

endmodule
