module TopModule (
  input clk,
  input L,
  input q_in,
  input r_in,
  output reg Q
);

  // One bit-slice of full_module: a 2:1 mux (L selects load value r_in vs the
  // feedback q_in) feeding a D flip-flop clocked on the rising edge.
  always @(posedge clk) begin
    Q <= L ? r_in : q_in;
  end


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    Q = 0;
  end

endmodule
