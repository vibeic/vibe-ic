module TopModule (
  input clk,
  input x,
  output z
);

  reg q1, q2, q3;

  initial begin
    q1 = 1'b0;
    q2 = 1'b0;
    q3 = 1'b0;
  end

  always @(posedge clk) begin
    q1 <= x ^ q1;      // XOR with own output
    q2 <= x & ~q2;     // AND with own complemented output
    q3 <= x | ~q3;     // OR with own complemented output
  end

  assign z = ~(q1 | q2 | q3);  // three-input NOR

endmodule
