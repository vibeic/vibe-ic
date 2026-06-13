module TopModule (
  input        in,
  input  [9:0] state,
  output [9:0] next_state,
  output       out1,
  output       out2
);

  assign next_state[0] = (state[0] | state[1] | state[2] | state[3] | state[4] | state[7] | state[8] | state[9]) & ~in;
  assign next_state[1] = (state[0] | state[8] | state[9]) & in;
  assign next_state[2] = state[1] & in;
  assign next_state[3] = state[2] & in;
  assign next_state[4] = state[3] & in;
  assign next_state[5] = state[4] & in;
  assign next_state[6] = state[5] & in;
  assign next_state[7] = (state[6] | state[7]) & in;
  assign next_state[8] = state[5] & ~in;
  assign next_state[9] = state[6] & ~in;

  assign out1 = state[8] | state[9];
  assign out2 = state[7] | state[9];

endmodule
