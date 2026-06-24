module TopModule (
  input clk,
  input d,
  output reg q
);

  reg qp;
  reg qn;

  always @(posedge clk)
    qp <= d;

  always @(negedge clk)
    qn <= d;

  always @(*)
    q <= clk ? qp : qn;


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
    qp = 0;
    qn = 0;
  end

endmodule
