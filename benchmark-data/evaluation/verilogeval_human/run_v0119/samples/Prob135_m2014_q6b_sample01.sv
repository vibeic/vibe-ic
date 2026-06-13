module TopModule (
  input [3:1] y,
  input w,
  output reg Y2
);
    // State codes y[3:1]: A=000,B=001,C=010,D=011,E=100,F=101.
    // Y2 = bit [2] (middle) of the next-state code.
    always @(*) begin
        case ({y, w})
            // A=000
            {3'b000, 1'b0}: Y2 = 1'b0;   // -> B(001)
            {3'b000, 1'b1}: Y2 = 1'b0;   // -> A(000)
            // B=001
            {3'b001, 1'b0}: Y2 = 1'b1;   // -> C(010)
            {3'b001, 1'b1}: Y2 = 1'b1;   // -> D(011)
            // C=010
            {3'b010, 1'b0}: Y2 = 1'b0;   // -> E(100)
            {3'b010, 1'b1}: Y2 = 1'b1;   // -> D(011)
            // D=011
            {3'b011, 1'b0}: Y2 = 1'b0;   // -> F(101)
            {3'b011, 1'b1}: Y2 = 1'b0;   // -> A(000)
            // E=100
            {3'b100, 1'b0}: Y2 = 1'b0;   // -> E(100)
            {3'b100, 1'b1}: Y2 = 1'b1;   // -> D(011)
            // F=101
            {3'b101, 1'b0}: Y2 = 1'b1;   // -> C(010)
            {3'b101, 1'b1}: Y2 = 1'b1;   // -> D(011)
            default: Y2 = 1'b0;
        endcase
    end
endmodule
