// Waveform decode: registered output, q <= ~a on each rising clk edge.
// No reset; q is x until the first edge (matches the waveform).
module TopModule (
  input clk,
  input a,
  output reg q
);

  always @(posedge clk)
    q <= ~a;

endmodule
