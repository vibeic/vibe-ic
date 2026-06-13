module TopModule (
  input [4:1] x,
  output logic f
);

  // K-map (columns x1x2, rows x3x4) minterms where f=1:
  // (x1,x2,x3,x4): 0000 0010 0011 0110 0111 1000 1010 1111
  always @(*) begin
    case ({x[1], x[2], x[3], x[4]})
      4'b0000: f = 1'b1;
      4'b0010: f = 1'b1;
      4'b0011: f = 1'b1;
      4'b0110: f = 1'b1;
      4'b0111: f = 1'b1;
      4'b1000: f = 1'b1;
      4'b1010: f = 1'b1;
      4'b1111: f = 1'b1;
      default: f = 1'b0;
    endcase
  end

endmodule
