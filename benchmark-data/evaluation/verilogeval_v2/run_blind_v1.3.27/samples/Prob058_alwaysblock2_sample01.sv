module TopModule (
    input  clk,
    input  a,
    input  b,
    output out_assign,
    output out_always_comb,
    output out_always_ff
);

    assign out_assign = a ^ b;

    reg out_always_comb_r;
    always @(*) begin
        out_always_comb_r = a ^ b;
    end
    assign out_always_comb = out_always_comb_r;

    reg out_always_ff_r;
    always @(posedge clk) begin
        out_always_ff_r <= a ^ b;
    end
    assign out_always_ff = out_always_ff_r;


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    out_always_ff_r = 0;
  end

endmodule
