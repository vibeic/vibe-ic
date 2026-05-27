module TopModule (
  input clk,
  input a,
  input b,
  output q,
  output state
);
  reg c;

  always @(posedge clk) begin
    c <= (a & b) | (a & c) | (b & c);
  end

  assign q = a ^ b ^ c;
  assign state = c;

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    c = 0;
  end

endmodule
