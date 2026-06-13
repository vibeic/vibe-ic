module TopModule (
  input  in,
  input  [3:0] state,
  output [3:0] next_state,
  output out
);

  // One-hot: A=state[0], B=state[1], C=state[2], D=state[3]
  assign next_state[0] = (state[0] & ~in) | (state[2] & ~in);
  assign next_state[1] = (state[0] &  in) | (state[1] &  in) | (state[3] & in);
  assign next_state[2] = (state[1] & ~in) | (state[3] & ~in);
  assign next_state[3] = (state[2] &  in);

  assign out = state[3];

endmodule
