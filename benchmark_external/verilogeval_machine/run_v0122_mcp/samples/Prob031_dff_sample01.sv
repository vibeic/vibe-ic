// Prob031_dff — single D flip-flop, no reset. q <= d on posedge clk.
// Power-up q is unknown; modeled with a separate initial block (not decl-init,
// which would trip Verilator PROCASSINIT).
module TopModule (
  input clk,
  input d,
  output reg q
);

  initial q = 1'bx;

  always @(posedge clk)
    q <= d;

endmodule
