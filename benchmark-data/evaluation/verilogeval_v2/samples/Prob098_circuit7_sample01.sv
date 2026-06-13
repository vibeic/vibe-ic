module TopModule (
  input  clk,
  input  a,
  output reg q
);
  // From waveform: at each rising clock edge, q takes the value ~a.
  always @(posedge clk) begin
    q <= ~a;
  end
endmodule
