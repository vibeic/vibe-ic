module TopModule (
  input clk,
  input x,
  input [2:0] y,
  output reg Y0,
  output reg z
);

  // Next-state bit 0 (Y[0]) as combinational function of present state y and x
  always @(*) begin
    case (y)
      3'b000: Y0 = x ? 1'b1 : 1'b0;  // ->001 / ->000
      3'b001: Y0 = x ? 1'b0 : 1'b1;  // ->100 / ->001
      3'b010: Y0 = x ? 1'b1 : 1'b0;  // ->001 / ->010
      3'b011: Y0 = x ? 1'b0 : 1'b1;  // ->010 / ->001
      3'b100: Y0 = x ? 1'b0 : 1'b1;  // ->100 / ->011
      default: Y0 = 1'b0;
    endcase
  end

  // Output z is 1 in states 011 and 100
  always @(*) begin
    case (y)
      3'b011:  z = 1'b1;
      3'b100:  z = 1'b1;
      default: z = 1'b0;
    endcase
  end

endmodule
