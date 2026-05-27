module TopModule (
  input d,
  input done_counting,
  input ack,
  input [9:0] state, // 10-bit one-hot current state
  output B3_next,
  output S_next,
  output S1_next,
  output Count_next,
  output Wait_next,
  output done,
  output counting,
  output shift_ena
);
  // state bit assignment:
  // [0]=S [1]=S1 [2]=S11 [3]=S110 [4]=B0 [5]=B1 [6]=B2 [7]=B3 [8]=Count [9]=Wait

  // next-state signals (by inspection of incoming transitions)
  assign B3_next    = state[6];                                  // from B2 always
  assign S_next     = (state[0] & ~d) | (state[1] & ~d) |
                      (state[3] & ~d) | (state[9] & ack);
  assign S1_next    = (state[0] & d);  // only S --d=1--> S1 enters S1 (S11 self-loops)
  assign Count_next = state[7] | (state[8] & ~done_counting);
  assign Wait_next  = (state[8] & done_counting) | (state[9] & ~ack);

  // output logic (Moore)
  assign shift_ena = state[4] | state[5] | state[6] | state[7]; // B0..B3
  assign counting  = state[8];                                  // Count
  assign done      = state[9];                                  // Wait
endmodule
