module TopModule (
  input [4:1] x,
  output logic f
);

  // Case literal bit order is {x[4],x[3],x[2],x[1]}.
  // f=1 minterms (x1,x2,x3,x4) from the Karnaugh map:
  //   0000,0010,1000,1001,1010,1100,1101,1111
  always @(*) begin
    case (x)
      4'b0000: f = 1'b1;  // x1x2x3x4 = 0000
      4'b0100: f = 1'b1;  // x1x2x3x4 = 0010
      4'b0001: f = 1'b1;  // x1x2x3x4 = 1000
      4'b1001: f = 1'b1;  // x1x2x3x4 = 1001
      4'b0101: f = 1'b1;  // x1x2x3x4 = 1010
      4'b0011: f = 1'b1;  // x1x2x3x4 = 1100
      4'b1011: f = 1'b1;  // x1x2x3x4 = 1101
      4'b1111: f = 1'b1;  // x1x2x3x4 = 1111
      default: f = 1'b0;
    endcase
  end

endmodule
