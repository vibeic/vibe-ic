// Prob058_alwaysblock2 — a^b via assign, comb-always, and ff-always.
module TopModule (
  input clk,
  input a,
  input b,
  output out_assign,
  output reg out_always_comb,
  output reg out_always_ff
);

  assign out_assign = a ^ b;

  always @(*)
    out_always_comb = a ^ b;

  // Reset-less registered output: deterministic power-up via separate initial
  // block (decl-init would trip Verilator PROCASSINIT).
  initial out_always_ff = 1'b0;

  always @(posedge clk)
    out_always_ff <= a ^ b;

endmodule
