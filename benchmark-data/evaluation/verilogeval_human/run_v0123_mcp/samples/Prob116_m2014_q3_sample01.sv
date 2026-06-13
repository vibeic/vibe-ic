module TopModule (
  input [4:1] x,
  output logic f
);
  // f over {x1,x2,x3,x4}. Care=1 minterms set to 1; care=0 and don't-cares set to 0.
  always @(*) begin
    case ({x[1], x[2], x[3], x[4]})
      4'b0010: f = 1'b1;
      4'b0011: f = 1'b1;
      4'b0110: f = 1'b1;
      4'b0111: f = 1'b1;
      4'b1101: f = 1'b1;
      default: f = 1'b0;
    endcase
  end
endmodule
