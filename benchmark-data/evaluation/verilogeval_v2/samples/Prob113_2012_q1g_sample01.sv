module TopModule (
  input  [3:0] x,
  output       f
);
  reg r;
  always @(*) begin
    case (x)
      4'd0,4'd1,4'd4,4'd5,4'd6,4'd12,4'd14,4'd15: r = 1'b1;
      default: r = 1'b0;
    endcase
  end
  assign f = r;
endmodule
