module TopModule (
  input in,
  input [3:0] state,
  output reg [3:0] next_state,
  output out
);

  // one-hot bit aliases: A=0, B=1, C=2, D=3
  always @(*) begin
    next_state[0] = in ? 1'b0 : (state[0] | state[2]);
    next_state[1] = in ? (state[0] | state[1] | state[3]) : 1'b0;
    next_state[2] = in ? 1'b0 : (state[1] | state[3]);
    next_state[3] = in ? state[2] : 1'b0;
  end

  assign out = state[3];

endmodule
