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
    // One-hot bit assignment:
    // [0]=S [1]=S1 [2]=S11 [3]=S110 [4]=B0 [5]=B1 [6]=B2 [7]=B3 [8]=Count [9]=Wait

    // Next-state signals (OR of incoming transitions)
    assign S_next     = (~d & state[0]) | (~d & state[1]) | (~d & state[3]) | (ack & state[9]);
    assign S1_next    =  d & state[0];
    assign B3_next    =  state[6];
    assign Count_next =  state[7] | (~done_counting & state[8]);
    assign Wait_next  = (done_counting & state[8]) | (~ack & state[9]);

    // Moore outputs
    assign shift_ena = state[4] | state[5] | state[6] | state[7];
    assign counting  = state[8];
    assign done      = state[9];
endmodule
