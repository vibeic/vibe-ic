module TopModule (
    input  clk,
    input  L,
    input  q_in,
    input  r_in,
    output reg Q
);

    // One bit-slice of full_module: a 2:1 mux selected by L feeding a
    // posedge D flip-flop. L=1 loads r_in (the r bit); L=0 takes q_in (the
    // shift-computed next bit wired in by the parent's three instances).
    always @(posedge clk)
        Q <= L ? r_in : q_in;


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    Q = 0;
  end

endmodule
