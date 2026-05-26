module TopModule (
    input        in,
    input  [3:0] state,
    output [3:0] next_state,
    output       out
);

    // One-hot: A=state[0], B=state[1], C=state[2], D=state[3]
    // Next state in=0 / in=1:
    //   A -> A,B
    //   B -> C,B
    //   C -> A,D
    //   D -> C,B
    assign next_state[0] = (state[0] & ~in) | (state[2] & ~in);            // A
    assign next_state[1] = (state[0] & in)  | (state[1] & in) | (state[3] & in); // B
    assign next_state[2] = (state[1] & ~in) | (state[3] & ~in);            // C
    assign next_state[3] = (state[2] & in);                                // D

    assign out = state[3]; // output 1 only in state D

endmodule
