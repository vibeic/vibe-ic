module TopModule (
  input clk,
  input x,
  output z
);

  // Three D flip-flops, each driven by a 2-input gate whose second input
  // is that flop's own (or complemented) output. Outputs NOR'd to z.
  reg fa, fb, fc;

  always @(posedge clk) begin
    fa <= x ^ fa;   // XOR, second input = its own output
    fb <= x & ~fb;  // AND, second input = its complemented output
    fc <= x | ~fc;  // OR,  second input = its complemented output
  end

  assign z = ~(fa | fb | fc);


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    fa = 0;
    fb = 0;
    fc = 0;
  end

endmodule
