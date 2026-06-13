module TopModule (
  input        d,
  input        done_counting,
  input        ack,
  input  [9:0] state,        // one-hot: [0]=S [1]=S1 [2]=S11 [3]=S110 [4]=B0 [5]=B1 [6]=B2 [7]=B3 [8]=Count [9]=Wait
  output       B3_next,
  output       S_next,
  output       S1_next,
  output       Count_next,
  output       Wait_next,
  output       done,
  output       counting,
  output       shift_ena
);

  // Next-state signals by inspection (OR of all transitions landing on the target).
  assign S_next     = (state[0] & ~d) | (state[1] & ~d) | (state[3] & ~d) | (state[9] & ack);
  assign S1_next    =  state[0] & d;
  assign B3_next    =  state[6];                                  // B2 -> B3 (always)
  assign Count_next =  state[7] | (state[8] & ~done_counting);    // B3 -> Count, Count holds
  assign Wait_next  = (state[8] & done_counting) | (state[9] & ~ack);

  // Moore outputs (function of current state only).
  assign shift_ena = state[4] | state[5] | state[6] | state[7];   // B0..B3
  assign counting  = state[8];                                    // Count
  assign done      = state[9];                                    // Wait

endmodule
