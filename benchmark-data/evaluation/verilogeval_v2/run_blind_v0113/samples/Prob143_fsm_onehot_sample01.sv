module TopModule(
    input         in,
    input  [9:0]  state,
    output [9:0]  next_state,
    output        out1,
    output        out2
);
    // One-hot transition logic: next_state[k] = OR of all transitions into Sk.
    // S0<-(S0,S1,S2,S3,S4,S7,S8,S9)&~in
    assign next_state[0] = (state[0] | state[1] | state[2] | state[3] |
                            state[4] | state[7] | state[8] | state[9]) & ~in;
    // S1<-(S0,S8,S9)&in
    assign next_state[1] = (state[0] | state[8] | state[9]) & in;
    // S2<-S1&in
    assign next_state[2] = state[1] & in;
    // S3<-S2&in
    assign next_state[3] = state[2] & in;
    // S4<-S3&in
    assign next_state[4] = state[3] & in;
    // S5<-S4&in
    assign next_state[5] = state[4] & in;
    // S6<-S5&in
    assign next_state[6] = state[5] & in;
    // S7<-(S6,S7)&in
    assign next_state[7] = (state[6] | state[7]) & in;
    // S8<-S5&~in
    assign next_state[8] = state[5] & ~in;
    // S9<-S6&~in
    assign next_state[9] = state[6] & ~in;

    // Outputs (Moore on current state)
    assign out1 = state[8] | state[9];
    assign out2 = state[7] | state[9];
endmodule
