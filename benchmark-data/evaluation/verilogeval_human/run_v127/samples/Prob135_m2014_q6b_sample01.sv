module TopModule (
  input  [3:1] y,
  input  w,
  output reg Y2
);

  // State codes y[3:1]: A=000 B=001 C=010 D=011 E=100 F=101.
  // Y2 = middle bit y[2] of the NEXT-state code, read row-by-row.
  // {y[3],y[2],y[1]} is the present-state code; the literal bits map MSB->y[3].
  always @(*) begin
    case (y)
      3'b000: Y2 = w ? 1'b0 : 1'b0;  // A: w=1->A(000), w=0->B(001)
      3'b001: Y2 = w ? 1'b1 : 1'b1;  // B: w=1->D(011), w=0->C(010)
      3'b010: Y2 = w ? 1'b1 : 1'b0;  // C: w=1->D(011), w=0->E(100)
      3'b011: Y2 = w ? 1'b0 : 1'b0;  // D: w=1->A(000), w=0->F(101)
      3'b100: Y2 = w ? 1'b1 : 1'b0;  // E: w=1->D(011), w=0->E(100)
      3'b101: Y2 = w ? 1'b1 : 1'b1;  // F: w=1->D(011), w=0->C(010)
      default: Y2 = 1'b0;            // unused codes -> don't-care
    endcase
  end

endmodule
