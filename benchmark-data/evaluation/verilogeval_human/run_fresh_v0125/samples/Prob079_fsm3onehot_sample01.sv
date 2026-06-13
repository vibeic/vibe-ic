module TopModule (
  input in,
  input [3:0] state,
  output reg [3:0] next_state,
  output out
);

  // one-hot: A=state[0], B=state[1], C=state[2], D=state[3]
  // Transitions (Next in=0, in=1):
  //   A: A, B ; B: C, B ; C: A, D ; D: C, B
  // next_state by inspection (OR of all transitions reaching each state):
  //   A_next = (A & ~in) | (C & ~in)
  //   B_next = (A & in)  | (B & in)  | (D & in)
  //   C_next = (B & ~in) | (D & ~in)
  //   D_next = (C & in)
  assign next_state[0] = (state[0] & ~in) | (state[2] & ~in);
  assign next_state[1] = (state[0] &  in) | (state[1] & in) | (state[3] & in);
  assign next_state[2] = (state[1] & ~in) | (state[3] & ~in);
  assign next_state[3] = (state[2] &  in);

  // output: only state D asserts out
  assign out = state[3];

endmodule
