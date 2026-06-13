module TopModule (
  input clk,
  input reset,
  input x,
  output reg z
);

  reg [2:0] y, ynext;

  always @(*) begin
    case (y)
      3'b000: ynext = x ? 3'b001 : 3'b000;
      3'b001: ynext = x ? 3'b100 : 3'b001;
      3'b010: ynext = x ? 3'b001 : 3'b010;
      3'b011: ynext = x ? 3'b010 : 3'b001;
      3'b100: ynext = x ? 3'b100 : 3'b011;
      default: ynext = 3'b000;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      y <= 3'b000;
    else
      y <= ynext;
  end

  always @(*) begin
    case (y)
      3'b011: z = 1'b1;
      3'b100: z = 1'b1;
      default: z = 1'b0;
    endcase
  end

endmodule
