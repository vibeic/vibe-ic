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
    // one-hot bit names
    localparam S    = 0;
    localparam S1   = 1;
    localparam S11  = 2;
    localparam S110 = 3;
    localparam B0   = 4;
    localparam B1   = 5;
    localparam B2   = 6;
    localparam B3   = 7;
    localparam CNT  = 8;
    localparam WT   = 9;

    // next-state assert signals (OR of per-state transition terms)
    assign S_next     = (~d & state[S]) | (~d & state[S1]) | (~d & state[S110]) | (ack & state[WT]);
    assign S1_next    = ( d & state[S]);
    assign B3_next    = state[B2];
    assign Count_next = state[B3];
    assign Wait_next  = (done_counting & state[CNT]);

    // Moore output logic (function of current state)
    assign shift_ena = state[B0] | state[B1] | state[B2] | state[B3];
    assign counting  = state[CNT];
    assign done      = state[WT];
endmodule
