module TopModule (
    input  clk,
    input  d,
    input  r,
    output reg q
);

    always @(posedge clk) begin
        if (r)
            q <= 1'b0;
        else
            q <= d;
    end


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
