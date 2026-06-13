module TopModule (
    input         in,
    input  [9:0]  state,
    output [9:0]  next_state,
    output        out1,
    output        out2
);
    // One-hot next-state logic by inspection. next_state[k] is the OR of all
    // transitions that lead to state Sk. State is treated as possibly multiple
    // active bits; OR contributions from each active source state.
    // Transitions:
    //  S0:0->S0,1->S1 ; S1:0->S0,1->S2 ; S2:0->S0,1->S3 ; S3:0->S0,1->S4
    //  S4:0->S0,1->S5 ; S5:0->S8,1->S6 ; S6:0->S9,1->S7 ; S7:0->S0,1->S7
    //  S8:0->S0,1->S1 ; S9:0->S0,1->S1
    assign next_state[0] = (~in) & (state[0]|state[1]|state[2]|state[3]|state[4]|state[7]|state[8]|state[9]);
    assign next_state[1] = in & (state[0]|state[8]|state[9]);
    assign next_state[2] = in & state[1];
    assign next_state[3] = in & state[2];
    assign next_state[4] = in & state[3];
    assign next_state[5] = in & state[4];
    assign next_state[6] = in & state[5];
    assign next_state[7] = (in & state[6]) | (in & state[7]);
    assign next_state[8] = (~in) & state[5];
    assign next_state[9] = (~in) & state[6];

    // Outputs (Moore on current state): S7 -> (out1,out2)=(0,1); S8 -> (1,0); S9 -> (1,1)
    assign out1 = state[8] | state[9];
    assign out2 = state[7] | state[9];
endmodule
