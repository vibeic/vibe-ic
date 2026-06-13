module TopModule (
  input [3:1] y,
  input w,
  output reg Y2
);

  // States A..F use codes y[3:1] = 000,001,010,011,100,101.
  // Y2 is the next-state value of the middle bit y[2].
  // Transition table (present {y3,y2,y1}, w) -> next; Y2 = next y[2].
  always @(*) begin
    case (y)
      3'b000: Y2 = w ? 1'b0 : 1'b0; // A: w0->B(001) Y2=0 ; w1->A(000) Y2=0
      3'b001: Y2 = w ? 1'b1 : 1'b1; // B: w0->C(010) Y2=1 ; w1->D(011) Y2=1
      3'b010: Y2 = w ? 1'b1 : 1'b0; // C: w0->E(100) Y2=0 ; w1->D(011) Y2=1
      3'b011: Y2 = w ? 1'b0 : 1'b0; // D: w0->F(101) Y2=0 ; w1->A(000) Y2=0
      3'b100: Y2 = w ? 1'b1 : 1'b0; // E: w0->E(100) Y2=0 ; w1->D(011) Y2=1
      3'b101: Y2 = w ? 1'b1 : 1'b1; // F: w0->C(010) Y2=1 ; w1->D(011) Y2=1
      default: Y2 = 1'b0;
    endcase
  end

endmodule
