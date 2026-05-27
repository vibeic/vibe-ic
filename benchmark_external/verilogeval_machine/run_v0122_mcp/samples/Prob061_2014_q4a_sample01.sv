// Prob061_2014_q4a — 1-bit register with load(L)/enable(E) controls.
// L has priority: L=1 -> Q<=R. L=0 -> if E load w, else hold.
//   Q <= L ? R : (E ? w : Q)
module TopModule (
  input clk,
  input w,
  input R,
  input E,
  input L,
  output reg Q
);

  // Reset-less registered output: deterministic power-up via separate initial
  // block (decl-init would trip Verilator PROCASSINIT).
  initial Q = 1'b0;

  always @(posedge clk) begin
    if (L)
      Q <= R;
    else if (E)
      Q <= w;
    // E low and L low: hold
  end

endmodule
