module TopModule (
  input        clk,
  input        shift_ena,
  input        count_ena,
  input        data,
  output reg [3:0] q
);
  always @(posedge clk) begin
    if (shift_ena)
      q <= {q[2:0], data};
    else if (count_ena)
      q <= q - 4'd1;
    else
      q <= q;
  end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
