module TopModule (
  input        in,
  input  [3:0] state,
  output [3:0] next_state,
  output       out
);

  // One-hot: A=state[0], B=state[1], C=state[2], D=state[3]
  // Next-state by inspection:
  //  A_next : in=0 from A; in=0 from C  -> ~in & (A | C)
  //  B_next : in=1 from A; in=1 from B; in=1 from D -> in & (A | B | D)
  //  C_next : in=0 from B; in=0 from D -> ~in & (B | D)
  //  D_next : in=1 from C -> in & C
  assign next_state[0] = ~in & (state[0] | state[2]);
  assign next_state[1] =  in & (state[0] | state[1] | state[3]);
  assign next_state[2] = ~in & (state[1] | state[3]);
  assign next_state[3] =  in & state[2];

  // Output high only in state D
  assign out = state[3];

endmodule
