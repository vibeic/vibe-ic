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
    // one-hot index map
    localparam S=0, S1=1, S11=2, S110=3, B0=4, B1=5, B2=6, B3=7, Count=8, Wait=9;

    // next-state indicators (OR of all incoming transitions)
    assign S_next     = (state[S]   & ~d) | (state[S1] & ~d) | (state[S110] & ~d) | (state[Wait] & ack);
    assign S1_next    = (state[S]   &  d);
    assign B3_next    =  state[B2];                                   // B2 -> B3 always
    assign Count_next =  state[B3] | (state[Count] & ~done_counting); // B3 -> Count, Count holds
    assign Wait_next  = (state[Count] & done_counting) | (state[Wait] & ~ack);

    // Moore outputs
    assign shift_ena = state[B0] | state[B1] | state[B2] | state[B3];
    assign counting  = state[Count];
    assign done      = state[Wait];
endmodule
