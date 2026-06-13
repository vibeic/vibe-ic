module TopModule (
  input [3:1] y,
  input w,
  output reg Y2
);

  // State codes y[3:1]: A=000 B=001 C=010 D=011 E=100 F=101
  // Y2 is bit y[2] of the next state.
  reg [3:1] ynext;

  always @(*) begin
    case (y)
      3'b000: ynext = w ? 3'b000 : 3'b001; // A
      3'b001: ynext = w ? 3'b011 : 3'b010; // B
      3'b010: ynext = w ? 3'b011 : 3'b100; // C
      3'b011: ynext = w ? 3'b000 : 3'b101; // D
      3'b100: ynext = w ? 3'b011 : 3'b100; // E
      3'b101: ynext = w ? 3'b011 : 3'b010; // F
      default: ynext = 3'b000;
    endcase
    Y2 = ynext[2];
  end

endmodule
