module TopModule (
  input  clk,
  input  x,
  output z
);
  reg q_xor, q_and, q_or;

  always @(posedge clk) begin
    q_xor <= x ^ q_xor;   // XOR with own FF output
    q_and <= x & ~q_and;  // AND with complemented FF output
    q_or  <= x | ~q_or;   // OR with complemented FF output
  end

  assign z = ~(q_xor | q_and | q_or);

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q_xor = 0;
    q_and = 0;
    q_or = 0;
  end

endmodule
