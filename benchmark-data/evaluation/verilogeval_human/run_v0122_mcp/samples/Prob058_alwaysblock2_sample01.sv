// XOR of a,b built three ways: continuous assign, combinational always,
// and a clocked always (registered, one-cycle delayed). No reset.
module TopModule (
  input clk,
  input a,
  input b,
  output out_assign,
  output reg out_always_comb,
  output reg out_always_ff
);

  // Reset-less registered output: separate initial block for power-up.
  initial out_always_ff = 1'b0;

  assign out_assign = a ^ b;

  always @(*)
    out_always_comb = a ^ b;

  always @(posedge clk)
    out_always_ff <= a ^ b;

endmodule
