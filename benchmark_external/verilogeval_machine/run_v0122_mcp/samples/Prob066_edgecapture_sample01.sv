// Prob066_edgecapture — 32-bit falling-edge capture register.
// d_last holds previous in. out |= (~in & d_last) captures 1->0 edges.
// Synchronous reset (checked inside posedge-clk block) clears out to 0.
module TopModule (
  input clk,
  input reset,
  input [31:0] in,
  output reg [31:0] out
);

  reg [31:0] d_last;

  always @(posedge clk) begin
    if (reset)
      out <= 32'b0;
    else
      out <= out | (~in & d_last);
    d_last <= in;
  end

endmodule
