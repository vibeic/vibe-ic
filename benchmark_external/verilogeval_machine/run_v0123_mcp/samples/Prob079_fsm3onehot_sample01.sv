module TopModule (
  input in,
  input [3:0] state,
  output reg [3:0] next_state,
  output out
);
  // one-hot index mapping: A=0, B=1, C=2, D=3
  localparam A = 0, B = 1, C = 2, D = 3;
  always @(*) begin
    next_state[A] = in ? 1'b0 : (state[A] | state[C]);
    next_state[B] = in ? (state[A] | state[B] | state[D]) : 1'b0;
    next_state[C] = in ? 1'b0 : (state[B] | state[D]);
    next_state[D] = in ? state[C] : 1'b0;
  end
  assign out = state[D];
endmodule
