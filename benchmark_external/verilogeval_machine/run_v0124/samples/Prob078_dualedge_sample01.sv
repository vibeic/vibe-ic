module TopModule (
  input clk,
  input d,
  output reg q
);
  reg qp, qn;
  always @(posedge clk)
    qp <= d;
  always @(negedge clk)
    qn <= d;
  always @(*)
    q = clk ? qp : qn;
endmodule
