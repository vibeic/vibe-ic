module TopModule (
    input        clk,
    input  [7:0] in,
    output reg [7:0] pedge
);
    reg [7:0] in_prev;
    always @(posedge clk) begin
        in_prev <= in;
        pedge   <= in & ~in_prev;
    end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    pedge = 0;
  end

endmodule
