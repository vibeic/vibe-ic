module TopModule (
  input      clk,
  input      a,
  output reg q
);
  // q captures ~a on each rising clock edge (one-cycle delayed inverter)
  always @(posedge clk)
    q <= ~a;
endmodule
