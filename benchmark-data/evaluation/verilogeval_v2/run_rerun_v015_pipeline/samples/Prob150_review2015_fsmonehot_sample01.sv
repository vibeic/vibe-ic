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
    // One-hot indices:
    //  S=0 S1=1 S11=2 S110=3 B0=4 B1=5 B2=6 B3=7 Count=8 Wait=9

    // next-state == B3 : only from B2 (always advances)
    assign B3_next = state[6];

    // next-state == S : S(d=0), S1(d=0), S110(d=0), Wait(ack=1)
    assign S_next = (state[0] & ~d) | (state[1] & ~d) | (state[3] & ~d) |
                    (state[9] & ack);

    // next-state == S1 : from S on d=1
    assign S1_next = state[0] & d;

    // next-state == Count : from B3 (always advances)
    assign Count_next = state[7];

    // next-state == Wait : Count on done_counting=1, Wait on ack=0
    assign Wait_next = (state[8] & done_counting) | (state[9] & ~ack);

    // Moore outputs
    assign done      = state[9];
    assign counting  = state[8];
    assign shift_ena = state[4] | state[5] | state[6] | state[7];
endmodule
