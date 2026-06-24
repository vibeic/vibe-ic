module TopModule (
    input  clk,
    input  a,
    output reg [2:0] q
);

  always @(posedge clk)
    if (a)
      q <= 4;
    else if (q == 6)
      q <= 0;
    else
      q <= q + 1'b1;

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
