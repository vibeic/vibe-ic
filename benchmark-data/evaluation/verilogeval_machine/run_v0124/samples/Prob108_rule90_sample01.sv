module TopModule (
  input clk,
  input load,
  input [511:0] data,
  output reg [511:0] q
);
  always @(posedge clk) begin
    if (load)
      q <= data;
    else
      q <= q[$bits(q)-1:1] ^ {q[$bits(q)-2:0], 1'b0};
  end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
