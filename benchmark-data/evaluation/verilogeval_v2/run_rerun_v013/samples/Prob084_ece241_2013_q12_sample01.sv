module TopModule (
  input  clk,
  input  enable,
  input  S,
  input  A,
  input  B,
  input  C,
  output Z
);

  reg [7:0] Q;

  // Shift register: S feeds Q[0], bits shift toward Q[7].
  always @(posedge clk) begin
    if (enable)
      Q <= {Q[6:0], S};
  end

  // Random-access read: ABC selects which flip-flop drives Z.
  // ABC=000 -> Q[0], 001 -> Q[1], ... 111 -> Q[7].
  assign Z = Q[{A, B, C}];

endmodule
