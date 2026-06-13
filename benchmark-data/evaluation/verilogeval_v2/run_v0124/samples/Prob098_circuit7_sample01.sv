module TopModule (
    input  clk,
    input  a,
    output reg q
);
    // Waveform: q registers the inverse of a on each posedge clk.
    always @(posedge clk)
        q <= ~a;

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
