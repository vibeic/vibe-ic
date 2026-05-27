module TopModule (
    input  [3:1] y,
    input  w,
    output reg Y2
);

    // Next-state bit y[2] for state codes A=000 .. F=101 (y[3:1]).
    always @(*) begin
        case (y)
            3'b000: Y2 = 1'b0;            // A: w0->B(001), w1->A(000)
            3'b001: Y2 = 1'b1;            // B: w0->C(010), w1->D(011)
            3'b010: Y2 = w ? 1'b1 : 1'b0; // C: w0->E(100), w1->D(011)
            3'b011: Y2 = 1'b0;            // D: w0->F(101), w1->A(000)
            3'b100: Y2 = w ? 1'b1 : 1'b0; // E: w0->E(100), w1->D(011)
            3'b101: Y2 = 1'b1;            // F: w0->C(010), w1->D(011)
            default: Y2 = 1'b0;
        endcase
    end

endmodule
