module TopModule (
  input [4:1] x,
  output logic f
);
  // f as sum of minterms over {x1,x2,x3,x4}, derived from the K-map ON-set.
  always @(*) begin
    case ({x[1], x[2], x[3], x[4]})
      4'b0000: f = 1'b1;
      4'b0010: f = 1'b1;
      4'b1000: f = 1'b1;
      4'b1001: f = 1'b1;
      4'b1010: f = 1'b1;
      4'b1100: f = 1'b1;
      4'b1101: f = 1'b1;
      4'b1111: f = 1'b1;
      default: f = 1'b0;
    endcase
  end
endmodule
