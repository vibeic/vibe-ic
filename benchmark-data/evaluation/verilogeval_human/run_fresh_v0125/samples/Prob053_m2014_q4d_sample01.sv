module TopModule (
  input clk,
  input in,
  output logic out
);

  always @(posedge clk) begin
    out <= in ^ out;
  end


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    out = 0;
  end

endmodule
