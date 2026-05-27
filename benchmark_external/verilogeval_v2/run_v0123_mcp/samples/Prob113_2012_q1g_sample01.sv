module TopModule (
  input  [3:0] x,
  output reg   f
);
  // K-map rows = x[2]x[3], cols = x[0]x[1]
  always @(*) begin
    case ({x[2], x[3], x[0], x[1]})
      // row 00 (x2=0,x3=0)
      4'b00_00: f = 1'b1;
      4'b00_01: f = 1'b0;
      4'b00_11: f = 1'b0;
      4'b00_10: f = 1'b1;
      // row 01 (x2=0,x3=1)
      4'b01_00: f = 1'b0;
      4'b01_01: f = 1'b0;
      4'b01_11: f = 1'b0;
      4'b01_10: f = 1'b0;
      // row 11 (x2=1,x3=1)
      4'b11_00: f = 1'b1;
      4'b11_01: f = 1'b1;
      4'b11_11: f = 1'b1;
      4'b11_10: f = 1'b0;
      // row 10 (x2=1,x3=0)
      4'b10_00: f = 1'b1;
      4'b10_01: f = 1'b1;
      4'b10_11: f = 1'b0;
      4'b10_10: f = 1'b1;
      default:  f = 1'b0;
    endcase
  end
endmodule
