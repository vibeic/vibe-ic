module TopModule (
    input        d,
    input        done_counting,
    input        ack,
    input  [9:0] state,
    output       B3_next,
    output       S_next,
    output       S1_next,
    output       Count_next,
    output       Wait_next,
    output       done,
    output       counting,
    output       shift_ena
);
    // state bits: S=0, S1=1, S11=2, S110=3, B0=4, B1=5, B2=6, B3=7, Count=8, Wait=9

    // next-state asserts by inspection (one-hot)
    assign S_next     = (state[0] & ~d) | (state[1] & ~d) | (state[3] & ~d) | (state[9] & ack);
    assign S1_next    = (state[0] &  d);
    assign B3_next    =  state[6];                       // B2 always -> B3
    assign Count_next =  state[7] | (state[8] & ~done_counting);
    assign Wait_next  = (state[8] & done_counting) | (state[9] & ~ack);

    // Moore outputs
    assign shift_ena = state[4] | state[5] | state[6] | state[7];
    assign counting  = state[8];
    assign done      = state[9];

endmodule
