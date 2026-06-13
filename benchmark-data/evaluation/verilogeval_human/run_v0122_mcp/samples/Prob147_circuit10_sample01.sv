module TopModule (
  input  clk,
  input  a,
  input  b,
  output q,
  output state
);

  // One flip-flop holding the carry. Next state = majority(a,b,state).
  reg st;

  initial st = 1'b0;        // power-up state observed as 0 (reset-less; avoids decl-init PROCASSINIT)

  always @(posedge clk)
    st <= (a & b) | (a & st) | (b & st);

  assign state = st;
  assign q     = a ^ b ^ st;   // combinational sum output

endmodule
