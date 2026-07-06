module TopModule (
    input      clk,
    input      L,
    input      q_in,
    input      r_in,
    output reg Q
);

    // One bit-slice of full_module: a 2:1 mux (select L, choices r_in vs
    // q_in feeding the rotate/xor network wired up outside this submodule)
    // followed by a D flip-flop.
    always @(posedge clk) begin
        if (L)
            Q <= r_in;
        else
            Q <= q_in;
    end


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    Q = 0;
  end

endmodule
