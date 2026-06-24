module TopModule (
    input  clk,
    input  a,
    input  b,
    output reg state,
    output q
);

  always @(posedge clk)
    state <= (a & b & ~state) | (a & b & state) | (a & ~b & state) | (~a & b & state);
  assign q = (~a & b & ~state) | (a & ~b & ~state) | (~a & ~b & state) | (a & b & state);

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    state = 0;
  end

endmodule
