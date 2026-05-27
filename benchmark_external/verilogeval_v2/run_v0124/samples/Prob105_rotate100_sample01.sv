module TopModule (
  input         clk,
  input         load,
  input  [1:0]  ena,
  input  [99:0] data,
  output reg [99:0] q
);
  always @(posedge clk) begin
    if (load)
      q <= data;
    else begin
      case (ena)
        2'b01: q <= {q[0], q[99:1]};   // rotate right by 1
        2'b10: q <= {q[98:0], q[99]};  // rotate left by 1
        default: q <= q;               // 2'b00 / 2'b11: hold
      endcase
    end
  end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
