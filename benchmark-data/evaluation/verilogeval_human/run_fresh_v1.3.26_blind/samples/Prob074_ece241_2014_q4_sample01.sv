module TopModule (
  input clk,
  input x,
  output z
);

  // Three D flip-flops, initially reset to zero.
  reg q_xor = 1'b0;   // driven by x XOR its own output
  reg q_and = 1'b0;   // driven by x AND its own complemented output
  reg q_or  = 1'b0;   // driven by x OR  its own complemented output

  always @(posedge clk) begin
    q_xor <= x ^ q_xor;
    q_and <= x & ~q_and;
    q_or  <= x | ~q_or;
  end

  // Outputs of the three flip-flops feed a three-input NOR.
  assign z = ~(q_xor | q_and | q_or);

endmodule
