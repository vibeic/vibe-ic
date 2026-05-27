module TopModule (
  input clk,
  input reset,
  input x,
  output reg z
);

  reg [2:0] y;

  // Next state logic from the state-assigned table.
  // present | next(x=0), next(x=1) | z
  // 000 | 000, 001 | 0
  // 001 | 001, 100 | 0
  // 010 | 010, 001 | 0
  // 011 | 001, 010 | 1
  // 100 | 011, 100 | 1
  reg [2:0] y_next;
  always @(*) begin
    case (y)
      3'b000: y_next = x ? 3'b001 : 3'b000;
      3'b001: y_next = x ? 3'b100 : 3'b001;
      3'b010: y_next = x ? 3'b001 : 3'b010;
      3'b011: y_next = x ? 3'b010 : 3'b001;
      3'b100: y_next = x ? 3'b100 : 3'b011;
      default: y_next = 3'b000;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      y <= 3'b000;
    else
      y <= y_next;
  end

  // Output z: 1 for states 011 and 100
  always @(*) begin
    case (y)
      3'b011: z = 1'b1;
      3'b100: z = 1'b1;
      default: z = 1'b0;
    endcase
  end

endmodule
