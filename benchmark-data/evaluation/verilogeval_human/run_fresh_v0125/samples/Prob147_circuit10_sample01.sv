module TopModule (
  input clk,
  input a,
  input b,
  output q,
  output state
);
  // One flip-flop. Next state is the majority of {a, b, state}.
  // Output q = a XOR b XOR state.
  reg sff;

  always @(posedge clk) begin
    sff <= (a & b) | (a & sff) | (b & sff);
  end

  assign state = sff;
  assign q = a ^ b ^ sff;

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    sff = 0;
  end

endmodule
