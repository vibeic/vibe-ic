module TopModule (
    input        in,
    input  [3:0] state,
    output [3:0] next_state,
    output       out
);
    // one-hot: state[0]=A, state[1]=B, state[2]=C, state[3]=D
    // next-state equations by inspection
    assign next_state[0] = (state[0] & ~in) | (state[2] & ~in);              // -> A
    assign next_state[1] = (state[0] |  state[1] | state[3]) & in;           // -> B
    assign next_state[2] = (state[1] |  state[3]) & ~in;                     // -> C
    assign next_state[3] =  state[2] & in;                                   // -> D

    // Moore output: 1 only in state D
    assign out = state[3];
endmodule
