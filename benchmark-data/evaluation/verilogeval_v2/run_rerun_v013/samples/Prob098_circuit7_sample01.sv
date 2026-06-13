module TopModule (
  input  clk,
  input  a,
  output q
);

  reg q_reg;

  // D flip-flop with D = ~a (q becomes ~a one cycle after sampling a)
  always @(posedge clk)
    q_reg <= ~a;

  assign q = q_reg;

endmodule
