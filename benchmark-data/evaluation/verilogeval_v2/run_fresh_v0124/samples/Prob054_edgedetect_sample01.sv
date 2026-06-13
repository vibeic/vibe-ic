module TopModule (
    input        clk,
    input  [7:0] in,
    output reg [7:0] pedge
);
    reg [7:0] in_prev;
    always @(posedge clk) begin
        in_prev <= in;
        pedge <= ~in_prev & in;   // 0 in prev cycle, 1 in current
    end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    pedge = 0;
  end

endmodule
