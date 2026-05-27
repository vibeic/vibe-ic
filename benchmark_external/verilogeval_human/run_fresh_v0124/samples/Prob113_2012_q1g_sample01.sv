module TopModule (
  input [4:1] x,
  output logic f
);
  // K-map: columns = x[1]x[2], rows = x[3]x[4] (Gray order 00,01,11,10).
  // Derived directly from the prompt's K-map grid. f=1 minterms over {x1,x2,x3,x4}:
  // 0000,1000 (row x3x4=00); 0011,0111,1111 (row 11); 0010,0110,1010 (row 10).
  always @(*) begin
    case ({x[1], x[2], x[3], x[4]})
      4'b0000: f = 1'b1;
      4'b1000: f = 1'b1;
      4'b0011: f = 1'b1;
      4'b0111: f = 1'b1;
      4'b1111: f = 1'b1;
      4'b0010: f = 1'b1;
      4'b0110: f = 1'b1;
      4'b1010: f = 1'b1;
      default: f = 1'b0;
    endcase
  end
endmodule
