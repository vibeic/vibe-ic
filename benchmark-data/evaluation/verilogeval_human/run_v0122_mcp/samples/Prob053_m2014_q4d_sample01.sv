// DFF fed by XOR(in, out). out <= in ^ out on posedge clk. No reset.
// Reset-less registered output: use a separate initial block for power-up
// (NOT a declaration initializer, which trips Verilator PROCASSINIT).
module TopModule (
  input clk,
  input in,
  output logic out
);

  initial out = 1'b0;

  always @(posedge clk)
    out <= in ^ out;

endmodule
