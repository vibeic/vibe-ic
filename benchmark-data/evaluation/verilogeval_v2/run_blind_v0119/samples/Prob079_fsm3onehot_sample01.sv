module TopModule(
    input  in,
    input  [3:0] state,   // one-hot: A=state[0],B=state[1],C=state[2],D=state[3]
    output [3:0] next_state,
    output out
);
    // Derived by inspection from the state-transition table:
    //   A -> A(in=0), B(in=1)
    //   B -> C(in=0), B(in=1)
    //   C -> A(in=0), D(in=1)
    //   D -> C(in=0), B(in=1)
    assign next_state[0] = (state[0] & ~in) | (state[2] & ~in);            // ->A
    assign next_state[1] = (state[0] &  in) | (state[1] & in) | (state[3] & in); // ->B
    assign next_state[2] = (state[1] & ~in) | (state[3] & ~in);            // ->C
    assign next_state[3] =  state[2] &  in;                                 // ->D

    assign out = state[3];   // Moore output: asserted only in state D
endmodule
