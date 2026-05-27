module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out
);

  // out=1 for {a,b,c,d} in:
  // 0000 0001 0010 0100 0110 0111 1000 1001 1011 1111
  reg out_r;
  always @(*) begin
    case ({a, b, c, d})
      4'b0000, 4'b0001, 4'b0010, 4'b0100, 4'b0110,
      4'b0111, 4'b1000, 4'b1001, 4'b1011, 4'b1111: out_r = 1'b1;
      default: out_r = 1'b0;
    endcase
  end

  assign out = out_r;

endmodule
