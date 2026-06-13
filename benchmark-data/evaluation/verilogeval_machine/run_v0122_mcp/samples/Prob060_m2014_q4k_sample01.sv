// Prob060_m2014_q4k — 4-bit shift register, sync active-low reset.
// Reset is checked inside the posedge-clk block -> synchronous (structure).
// Shift left, in -> LSB, out = MSB.
module TopModule (
  input clk,
  input resetn,
  input in,
  output out
);

  reg [3:0] sr;

  always @(posedge clk) begin
    if (!resetn)
      sr <= 4'b0;
    else
      sr <= {sr[2:0], in};
  end

  assign out = sr[3];

endmodule
