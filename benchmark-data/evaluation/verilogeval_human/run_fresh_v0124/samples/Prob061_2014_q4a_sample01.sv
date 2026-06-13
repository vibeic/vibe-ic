module TopModule (
  input clk,
  input w,
  input R,
  input E,
  input L,
  output reg Q
);

  // Two muxes feeding a D flip-flop:
  //  - E selects between hold (Q) and shift-in (w)
  //  - L selects between that result and the load value R (L has priority)
  wire shift_mux = E ? w : Q;
  wire d         = L ? R : shift_mux;

  always @(posedge clk) begin
    Q <= d;
  end


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    Q = 0;
  end

endmodule
