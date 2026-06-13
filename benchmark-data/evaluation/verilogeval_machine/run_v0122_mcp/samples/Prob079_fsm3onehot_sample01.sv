// Prob079_fsm3onehot — one-hot FSM next-state logic (A=0,B=1,C=2,D=3).
module TopModule (
  input in,
  input [3:0] state,
  output reg [3:0] next_state,
  output out
);

  // Pure combinational assigns (next_state declared reg for header conformance).
  always @(*) begin
    next_state[0] = ~in & (state[0] | state[2]);          // A
    next_state[1] =  in & (state[0] | state[1] | state[3]); // B
    next_state[2] = ~in & (state[1] | state[3]);          // C
    next_state[3] =  in &  state[2];                       // D
  end

  assign out = state[3];

endmodule
