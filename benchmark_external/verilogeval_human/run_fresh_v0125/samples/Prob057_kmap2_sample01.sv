module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out
);

  reg out_r;

  always @(*) begin
    case ({a, b, c, d})
      4'b0000: out_r = 1'b1;
      4'b0001: out_r = 1'b1;
      4'b0010: out_r = 1'b1;
      4'b0100: out_r = 1'b1;
      4'b0110: out_r = 1'b1;
      4'b0111: out_r = 1'b1;
      4'b1000: out_r = 1'b1;
      4'b1001: out_r = 1'b1;
      4'b1011: out_r = 1'b1;
      4'b1111: out_r = 1'b1;
      default: out_r = 1'b0;
    endcase
  end

  assign out = out_r;

endmodule
