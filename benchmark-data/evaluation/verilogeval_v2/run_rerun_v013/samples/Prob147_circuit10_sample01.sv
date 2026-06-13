module TopModule (
  input  clk,
  input  a,
  input  b,
  output q,
  output state
);

  reg state_r;

  always @(posedge clk) begin
    if (state_r)
      state_r <= a | b;
    else
      state_r <= b;
  end

  assign state = state_r;
  assign q     = a ^ b ^ state_r;

endmodule
