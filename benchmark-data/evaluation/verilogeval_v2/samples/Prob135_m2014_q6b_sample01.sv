module TopModule (
  input  [2:0] y,
  input  w,
  output Y1
);

  // States: A=000, B=001, C=010, D=011, E=100, F=101
  // Next-state where next y[1]=1 occurs for next state C(010) or D(011).
  // Next state = C : from B(w=0), F(w=0)
  // Next state = D : from B(w=1), C(w=1), E(w=1), F(w=1)
  reg [2:0] Y_next;

  always @(*) begin
    case (y)
      3'b000: Y_next = w ? 3'b000 : 3'b001; // A
      3'b001: Y_next = w ? 3'b011 : 3'b010; // B
      3'b010: Y_next = w ? 3'b011 : 3'b100; // C
      3'b011: Y_next = w ? 3'b000 : 3'b101; // D
      3'b100: Y_next = w ? 3'b011 : 3'b100; // E
      3'b101: Y_next = w ? 3'b011 : 3'b010; // F
      default: Y_next = 3'bxxx;
    endcase
  end

  assign Y1 = Y_next[1];

endmodule
