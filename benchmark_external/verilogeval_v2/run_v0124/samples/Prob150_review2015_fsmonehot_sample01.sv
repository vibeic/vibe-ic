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
    // One-hot encoding (S, S1, S11, S110, B0, B1, B2, B3, Count, Wait)
    //                    [0] [1]  [2]   [3]  [4] [5] [6] [7]   [8]    [9]

    // Next-state logic: OR every incoming edge (incl. self-loops / hold terms).
    // into S:    S(d=0), S1(d=0), S110(d=0), Wait(ack=1)
    assign S_next     = (state[0] & ~d) | (state[1] & ~d) | (state[3] & ~d) | (state[9] & ack);
    // into S1:   S(d=1)
    assign S1_next    =  state[0] & d;
    // into B3:   B2 (always)
    assign B3_next    =  state[6];
    // into Count: B3 (always), Count(done_counting=0)  -- self-hold
    assign Count_next =  state[7] | (state[8] & ~done_counting);
    // into Wait: Count(done_counting=1), Wait(ack=0)   -- self-hold
    assign Wait_next  = (state[8] & done_counting) | (state[9] & ~ack);

    // Moore outputs (function of current state only).
    assign shift_ena  = state[4] | state[5] | state[6] | state[7]; // B0..B3
    assign counting   = state[8];                                  // Count
    assign done       = state[9];                                  // Wait
endmodule
