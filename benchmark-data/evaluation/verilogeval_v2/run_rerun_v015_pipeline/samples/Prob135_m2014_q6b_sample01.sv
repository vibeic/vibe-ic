module TopModule (
    input  [2:0] y,
    input  w,
    output reg Y1
);

    // Next-state logic for bit y[1] only.
    // States A..F encoded 000..101. Y1 = next_state[1].
    always @(*) begin
        case (y)
            3'b000: Y1 = 1'b0;            // A: w0->B(001) w1->A(000)
            3'b001: Y1 = 1'b1;            // B: w0->C(010) w1->D(011)
            3'b010: Y1 = w ? 1'b1 : 1'b0; // C: w0->E(100) w1->D(011)
            3'b011: Y1 = 1'b0;            // D: w0->F(101) w1->A(000)
            3'b100: Y1 = w ? 1'b1 : 1'b0; // E: w0->E(100) w1->D(011)
            3'b101: Y1 = 1'b1;            // F: w0->C(010) w1->D(011)
            default: Y1 = 1'b0;
        endcase
    end

endmodule
