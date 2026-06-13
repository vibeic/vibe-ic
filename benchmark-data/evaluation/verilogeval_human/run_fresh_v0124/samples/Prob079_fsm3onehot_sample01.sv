module TopModule (
  input in,
  input [3:0] state,
  output reg [3:0] next_state,
  output out
);

  // one-hot: A=state[0], B=state[1], C=state[2], D=state[3]
  // Transitions:
  //   A: in=0->A, in=1->B
  //   B: in=0->C, in=1->B
  //   C: in=0->A, in=1->D
  //   D: in=0->C, in=1->B
  // Next-state by inspection (OR of all sources entering each state):
  //   next A = (A & ~in) | (C & ~in)
  //   next B = (A & in)  | (B & in) | (D & in)
  //   next C = (B & ~in) | (D & ~in)
  //   next D = (C & in)

  always @(*) begin
    next_state[0] = (state[0] & ~in) | (state[2] & ~in);
    next_state[1] = (state[0] &  in) | (state[1] & in) | (state[3] & in);
    next_state[2] = (state[1] & ~in) | (state[3] & ~in);
    next_state[3] = (state[2] &  in);
  end

  // output high only in state D
  assign out = state[3];

endmodule
