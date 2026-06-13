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

  // Shift register: S feeds Q[0], shifts toward Q[7] when enable is high.
  always @(posedge clk) begin
    if (enable)
      Q <= {Q[6:0], S};
  end

  // 8:1 mux: ABC = 000 -> Q[0], 001 -> Q[1], ...
  assign Z = Q[{A, B, C}];

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    Q = 0;
  end

endmodule
