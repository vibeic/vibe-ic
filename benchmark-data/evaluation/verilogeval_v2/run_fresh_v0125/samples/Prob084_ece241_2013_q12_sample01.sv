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

  // Shift register: S feeds Q[0]; shift toward higher index when enabled.
  always @(posedge clk) begin
    if (enable)
      Q <= {Q[6:0], S};
  end

  // Random-access read: ABC selects which flip-flop output drives Z.
  assign Z = Q[{A, B, C}];


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    Q = 0;
  end

endmodule
