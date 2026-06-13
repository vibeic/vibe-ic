module TopModule (
    input  clk,
    input  w,
    input  R,
    input  E,
    input  L,
    output reg Q
);
    always @(posedge clk) begin
        if (L)
            Q <= R;
        else if (E)
            Q <= w;
        else
            Q <= Q;
    end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    Q = 0;
  end

endmodule
