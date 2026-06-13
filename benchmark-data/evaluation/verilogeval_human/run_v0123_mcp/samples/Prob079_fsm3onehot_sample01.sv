module TopModule (
  input in,
  input [3:0] state,
  output reg [3:0] next_state,
  output out
);

  // One-hot: state[0]=A, state[1]=B, state[2]=C, state[3]=D
  always @(*) begin
    next_state[0] = (state[0] & ~in) | (state[2] & ~in);          // ->A
    next_state[1] = (state[0] & in) | (state[1] & in) | (state[3] & in); // ->B
    next_state[2] = (state[1] & ~in) | (state[3] & ~in);          // ->C
    next_state[3] = (state[2] & in);                              // ->D
  end

  assign out = state[3];

endmodule
