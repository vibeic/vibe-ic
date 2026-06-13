module TopModule (
  input  clk,
  input  x,
  input  [2:0] y,
  output Y0,
  output z
);

  reg [2:0] Y_next;

  always @(*) begin
    case (y)
      3'b000: Y_next = x ? 3'b001 : 3'b000;
      3'b001: Y_next = x ? 3'b100 : 3'b001;
      3'b010: Y_next = x ? 3'b001 : 3'b010;
      3'b011: Y_next = x ? 3'b010 : 3'b001;
      3'b100: Y_next = x ? 3'b100 : 3'b011;
      default: Y_next = 3'bxxx;
    endcase
  end

  assign Y0 = Y_next[0];

  // z is the Moore output of the present state y
  assign z = (y == 3'b011) || (y == 3'b100);

endmodule
