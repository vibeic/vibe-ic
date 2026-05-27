// Prob150_review2015_fsmonehot — combinational one-hot next-state/output logic.
// Bit map: S=0,S1=1,S11=2,S110=3,B0=4,B1=5,B2=6,B3=7,Count=8,Wait=9.
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

  localparam S=0, S1=1, S11=2, S110=3, B0=4, B1=5, B2=6, B3=7, COUNT=8, WAIT=9;

  assign done      = state[WAIT];
  assign counting  = state[COUNT];
  assign shift_ena = state[B3] | state[B2] | state[B1] | state[B0];

  assign B3_next    = state[B2];
  assign S_next     = (state[S] & ~d) | (state[S1] & ~d) | (state[S110] & ~d) | (state[WAIT] & ack);
  assign S1_next    = state[S] & d;
  assign Count_next = state[B3] | (state[COUNT] & ~done_counting);
  assign Wait_next  = (state[COUNT] & done_counting) | (state[WAIT] & ~ack);

endmodule
