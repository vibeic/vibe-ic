module TopModule (
  input clk,
  input a,
  output reg q
);
  // From waveform: q registers the inverse of a on each rising clock edge.
  always @(posedge clk) begin
    q <= ~a;
  end
endmodule
