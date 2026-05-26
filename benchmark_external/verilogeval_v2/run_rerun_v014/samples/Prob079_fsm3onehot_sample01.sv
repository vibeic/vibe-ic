module TopModule (
  input  in,
  input  [3:0] state,
  output [3:0] next_state,
  output out
);

  // one-hot: A=0001, B=0010, C=0100, D=1000
  // Next-state by inspection (sum of states that transition into each):
  //  A_next: from A(in=0) or C(in=0)
  //  B_next: from A(in=1) or B(in=1) or D(in=1)
  //  C_next: from B(in=0) or D(in=0)
  //  D_next: from C(in=1)
  assign next_state[0] = (state[0] & ~in) | (state[2] & ~in);
  assign next_state[1] = (state[0] & in) | (state[1] & in) | (state[3] & in);
  assign next_state[2] = (state[1] & ~in) | (state[3] & ~in);
  assign next_state[3] = (state[2] & in);

  // output asserted only in state D
  assign out = state[3];

endmodule
