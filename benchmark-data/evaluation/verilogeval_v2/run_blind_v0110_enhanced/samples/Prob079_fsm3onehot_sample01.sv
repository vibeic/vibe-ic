module TopModule(
    input  in,
    input  [3:0] state,
    output [3:0] next_state,
    output out
);
    // state one-hot: A=state[0], B=state[1], C=state[2], D=state[3]
    // A: 0->A,1->B   B: 0->C,1->B   C: 0->A,1->D   D: 0->C,1->B
    assign next_state[0] = (state[0] & ~in) | (state[2] & ~in);          // ->A
    assign next_state[1] = (state[0] & in) | (state[1] & in) | (state[3] & in); // ->B
    assign next_state[2] = (state[1] & ~in) | (state[3] & ~in);          // ->C
    assign next_state[3] = (state[2] & in);                             // ->D
    assign out = state[3];                                              // Moore output, 1 in D
endmodule
