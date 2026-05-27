module TopModule (
  input clk,
  input a,
  input b,
  output q,
  output state
);

  // One flip-flop. Next state: when state=0 require a&b to set; when state=1
  // require a|b to stay set. Output q = a XOR b XOR state.
  reg s;

  always @(posedge clk) begin
    if (s == 1'b0)
      s <= a & b;
    else
      s <= a | b;
  end

  assign state = s;
  assign q     = a ^ b ^ s;


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    s = 0;
  end

endmodule
