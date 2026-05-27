module TopModule (
  input clk,
  input j,
  input k,
  output reg Q
);
  always @(posedge clk)
    Q <= (j & ~Q) | (~k & Q);

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    Q = 0;
  end

endmodule
