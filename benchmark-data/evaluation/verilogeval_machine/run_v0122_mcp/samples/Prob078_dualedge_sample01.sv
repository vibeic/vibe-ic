// Prob078_dualedge — dual-edge FF: two edge-flops + clk-mux output.
// qp <- d @posedge, qn <- d @negedge, q = clk ? qp : qn.
module TopModule (
  input clk,
  input d,
  output reg q
);

  reg qp, qn;

  always @(posedge clk)
    qp <= d;

  always @(negedge clk)
    qn <= d;

  always @(*)
    q = clk ? qp : qn;

endmodule
