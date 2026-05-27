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

  // One-hot index map:
  //   (S, S1, S11, S110, B0, B1, B2, B3, Count, Wait) = state[0..9]
  // Next-state-is-X = OR of every incoming edge to X, including self-loops.

  // S_next: S--d=0-->S, S1--d=0-->S, S110--d=0-->S, Wait--ack=1-->S
  assign S_next     = (state[0] & ~d) | (state[1] & ~d) | (state[3] & ~d) | (state[9] & ack);

  // S1_next: S--d=1-->S1
  assign S1_next    = state[0] & d;

  // B3_next: B2--always-->B3
  assign B3_next    = state[6];

  // Count_next: B3--always-->Count, Count--done_counting=0-->Count (self-loop)
  assign Count_next = state[7] | (state[8] & ~done_counting);

  // Wait_next: Count--done_counting=1-->Wait, Wait--ack=0-->Wait (self-loop)
  assign Wait_next  = (state[8] & done_counting) | (state[9] & ~ack);

  // Moore outputs (function of current state only)
  assign shift_ena  = state[4] | state[5] | state[6] | state[7]; // B0,B1,B2,B3
  assign counting   = state[8];                                  // Count
  assign done       = state[9];                                  // Wait

endmodule
