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

  // 8-bit shift register, MSB shifted in first: S feeds Q[0], shifting up.
  always @(posedge clk) begin
    if (enable)
      Q <= {Q[6:0], S};
  end

  // Random-access read via 8-to-1 mux selected by {A,B,C}
  assign Z = Q[{A, B, C}];

endmodule
