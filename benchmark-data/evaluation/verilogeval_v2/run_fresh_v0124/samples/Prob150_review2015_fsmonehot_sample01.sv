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
    // One-hot encoding indices:
    // 0:S 1:S1 2:S11 3:S110 4:B0 5:B1 6:B2 7:B3 8:Count 9:Wait
    localparam S    = 0;
    localparam S1   = 1;
    localparam S11  = 2;
    localparam S110 = 3;
    localparam B0   = 4;
    localparam B1   = 5;
    localparam B2   = 6;
    localparam B3   = 7;
    localparam COUNT= 8;
    localparam WAIT = 9;

    // Next-state logic by inspection: each next-state bit is the OR over every
    // transition that LANDS in that state, of (source-state-bit & its condition).
    //
    // Incoming-transition inventory (from the prompt table):
    //   S    <- S(d=0), S1(d=0), S110(d=0), Wait(ack=1)
    //   S1   <- S(d=1)                          [S1 with d=1 goes to S11, NOT a self-loop]
    //   S11  <- S1(d=1), S11(d=1)
    //   S110 <- S11(d=0)
    //   B0   <- S110(d=1)
    //   B1   <- B0 ; B2 <- B1 ; B3 <- B2 ; Count <- B3 (unconditional advances)
    //   Count<- Count(done_counting=0)
    //   Wait <- Count(done_counting=1), Wait(ack=0)

    assign S_next  = (state[S] & ~d) | (state[S1] & ~d) | (state[S110] & ~d) | (state[WAIT] & ack);
    assign S1_next = (state[S] & d);
    assign B3_next = state[B2];
    assign Count_next = state[B3] | (state[COUNT] & ~done_counting);
    assign Wait_next  = (state[COUNT] & done_counting) | (state[WAIT] & ~ack);

    // Moore output logic (function of current state only).
    assign shift_ena = state[B0] | state[B1] | state[B2] | state[B3];
    assign counting  = state[COUNT];
    assign done      = state[WAIT];
endmodule
