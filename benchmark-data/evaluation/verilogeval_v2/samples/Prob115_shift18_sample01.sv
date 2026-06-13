module TopModule (
  input         clk,
  input         load,
  input         ena,
  input  [1:0]  amount,
  input  [63:0] data,
  output [63:0] q
);
  reg [63:0] r;
  always @(posedge clk) begin
    if (load)
      r <= data;
    else if (ena) begin
      case (amount)
        2'b00: r <= r << 1;
        2'b01: r <= r << 8;
        2'b10: r <= {r[63], r[63:1]};
        2'b11: r <= {{8{r[63]}}, r[63:8]};
        default: r <= r;
      endcase
    end
  end
  assign q = r;
endmodule
