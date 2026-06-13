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

    // State encoding (one-hot):
    // state[0]=S, [1]=S1, [2]=S11, [3]=S110,
    // [4]=B0, [5]=B1, [6]=B2, [7]=B3, [8]=Count, [9]=Wait

    // Next-state equations (combinational):
    //   S    <- S(d=0), S1(d=0), S110(d=0), Wait(ack=1)
    //   S1   <- S(d=1)
    //   B3   <- B2(always)
    //   Count<- B3(always), Count(done_counting=0)
    //   Wait <- Count(done_counting=1), Wait(ack=0)
    assign S_next     = (state[0] & ~d) | (state[1] & ~d) | (state[3] & ~d) | (state[9] & ack);
    assign S1_next    = (state[0] & d);
    assign B3_next    = state[6];
    assign Count_next = state[7] | (state[8] & ~done_counting);
    assign Wait_next  = (state[8] & done_counting) | (state[9] & ~ack);

    // Output logic (Moore):
    assign done      = state[9];
    assign counting  = state[8];
    assign shift_ena = state[4] | state[5] | state[6] | state[7];

endmodule
