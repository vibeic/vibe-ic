module TopModule (
    input  clk,
    input  a,
    input  b,
    output q,
    output state
);
    reg s;
    always @(posedge clk) begin
        s <= s ? (a | b) : (a & b);
    end
    assign state = s;
    assign q = a ^ b ^ s;

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    s = 0;
  end

endmodule
