module TopModule (
  input  in,
  input  [3:0] state,   // A=0001,B=0010,C=0100,D=1000
  output [3:0] next_state,
  output out
);
  // Derived by inspection from the one-hot transition table:
  // next_A: arrivals into A  -> A(in=0), C(in=0)
  assign next_state[0] = ~in & (state[0] | state[2]);
  // next_B: arrivals into B  -> A(in=1), B(in=1), D(in=1)
  assign next_state[1] =  in & (state[0] | state[1] | state[3]);
  // next_C: arrivals into C  -> B(in=0), D(in=0)
  assign next_state[2] = ~in & (state[1] | state[3]);
  // next_D: arrivals into D  -> C(in=1)
  assign next_state[3] =  in & state[2];

  assign out = state[3];   // Moore output: 1 only in state D
endmodule
