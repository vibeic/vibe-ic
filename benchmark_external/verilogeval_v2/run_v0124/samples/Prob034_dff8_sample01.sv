module TopModule (
  input  clk,
  input  [7:0] d,
  output reg [7:0] q
);
  always @(posedge clk) begin
    q <= d;
  end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
