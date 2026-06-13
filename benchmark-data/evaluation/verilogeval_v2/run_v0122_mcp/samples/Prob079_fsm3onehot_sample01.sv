module TopModule (
    input        in,
    input  [3:0] state,
    output [3:0] next_state,
    output       out
);

    // one-hot: state[0]=A, state[1]=B, state[2]=C, state[3]=D
    // next-state logic by inspection
    assign next_state[0] = (~in & state[0]) | (~in & state[2]);                 // ->A
    assign next_state[1] = ( in & state[0]) | ( in & state[1]) | ( in & state[3]); // ->B
    assign next_state[2] = (~in & state[1]) | (~in & state[3]);                 // ->C
    assign next_state[3] = ( in & state[2]);                                    // ->D

    assign out = state[3];   // Moore output: 1 only in state D

endmodule
