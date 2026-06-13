module TopModule (
  input clk,
  input x,
  input [2:0] y,
  output reg Y0,
  output reg z
);

  // Y0 = LSB of the next state given present state y and input x.
  // z depends only on present state (1 for states 011 and 100).
  reg [2:0] ns;
  always @(*) begin
    case (y)
      3'b000: ns = x ? 3'b001 : 3'b000;
      3'b001: ns = x ? 3'b100 : 3'b001;
      3'b010: ns = x ? 3'b001 : 3'b010;
      3'b011: ns = x ? 3'b010 : 3'b001;
      3'b100: ns = x ? 3'b100 : 3'b011;
      default: ns = 3'b000;
    endcase
    Y0 = ns[0];

    case (y)
      3'b011: z = 1'b1;
      3'b100: z = 1'b1;
      default: z = 1'b0;
    endcase
  end

endmodule
