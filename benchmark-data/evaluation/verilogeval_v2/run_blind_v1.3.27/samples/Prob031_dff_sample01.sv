module TopModule (
    input      clk,
    input      d,
    output reg q
);

    // Spec-defect note: the prompt's bullet list names 'q' as an input,
    // but a D flip-flop's q signal is by definition its registered output
    // (it cannot be driven externally and also be the flop's state).
    // Implementing q as the output is the only functionally sensible
    // realization of "a single D flip-flop" with ports clk, d, q.
    always @(posedge clk) begin
        q <= d;
    end


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
