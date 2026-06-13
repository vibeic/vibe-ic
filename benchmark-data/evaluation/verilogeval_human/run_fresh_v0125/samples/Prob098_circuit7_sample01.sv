module TopModule (
  input clk,
  input a,
  output reg q
);

  // Per waveform: q is the registered inverse of a (D flip-flop, D = ~a).
  always @(posedge clk) begin
    q <= ~a;
  end


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
