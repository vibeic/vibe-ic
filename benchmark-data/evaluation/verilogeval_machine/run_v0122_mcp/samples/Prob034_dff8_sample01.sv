// Prob034_dff8 — 8-bit register, no reset. q <= d on posedge clk.
// Power-up q = 8'h0 via a separate initial block (not decl-init, which
// would trip Verilator PROCASSINIT).
module TopModule (
  input clk,
  input [7:0] d,
  output reg [7:0] q
);

  initial q = 8'h0;

  always @(posedge clk)
    q <= d;

endmodule
