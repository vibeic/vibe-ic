module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out
);
  // index = {a,b,c,d}; out=1 for minterms 0,1,2,4,6,7,8,9,11,15
  reg r;
  always @(*) begin
    case ({a, b, c, d})
      4'd0:  r = 1'b1;
      4'd1:  r = 1'b1;
      4'd2:  r = 1'b1;
      4'd4:  r = 1'b1;
      4'd6:  r = 1'b1;
      4'd7:  r = 1'b1;
      4'd8:  r = 1'b1;
      4'd9:  r = 1'b1;
      4'd11: r = 1'b1;
      4'd15: r = 1'b1;
      default: r = 1'b0;
    endcase
  end
  assign out = r;
endmodule
