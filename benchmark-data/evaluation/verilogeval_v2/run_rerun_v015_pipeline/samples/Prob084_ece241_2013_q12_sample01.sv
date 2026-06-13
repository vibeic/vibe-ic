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
  // 8-bit shift register: S feeds Q[0] (MSB shifted in first), shift on enable.
  // Q[0] <= S, Q[k] <= Q[k-1].
  always @(posedge clk) begin
    if (enable)
      Q <= {Q[6:0], S};
  end
  // Random-access read: Z = Q[{A,B,C}]
  assign Z = Q[{A, B, C}];
endmodule
