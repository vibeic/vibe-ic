// 8-bit any-edge detector. anyedge[i] set the cycle after in[i] toggles
// (0->1 or 1->0). Register the previous value of in and XOR against the
// new value, all sampled on the rising edge. No reset.
module TopModule (
  input clk,
  input [7:0] in,
  output reg [7:0] anyedge
);

  reg [7:0] in_prev;

  // Reset-less registered outputs: power-up initializers for determinism.
  initial begin
    anyedge = 8'b0;
    in_prev = 8'b0;
  end

  always @(posedge clk) begin
    anyedge <= in ^ in_prev;
    in_prev <= in;
  end

endmodule
