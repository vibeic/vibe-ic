module TopModule (
  input  [4:1] x,
  output reg   f
);
  // K-map rows = x[3]x[4], cols = x[1]x[2]; don't-cares chosen for a simple cover.
  always @(*) begin
    case ({x[3], x[4], x[1], x[2]})
      // row 00 (x3=0,x4=0): d 0 d d
      4'b00_00: f = 1'b1;  // d
      4'b00_01: f = 1'b0;
      4'b00_11: f = 1'b0;  // d
      4'b00_10: f = 1'b1;  // d
      // row 01 (x3=0,x4=1): 0 d 1 0
      4'b01_00: f = 1'b0;
      4'b01_01: f = 1'b0;  // d
      4'b01_11: f = 1'b1;
      4'b01_10: f = 1'b0;
      // row 11 (x3=1,x4=1): 1 1 d d
      4'b11_00: f = 1'b1;
      4'b11_01: f = 1'b1;
      4'b11_11: f = 1'b1;  // d
      4'b11_10: f = 1'b1;  // d
      // row 10 (x3=1,x4=0): 1 1 0 d
      4'b10_00: f = 1'b1;
      4'b10_01: f = 1'b1;
      4'b10_11: f = 1'b0;
      4'b10_10: f = 1'b0;  // d
      default:  f = 1'b0;
    endcase
  end
endmodule
