module TopModule (
    input  [2:0] y,
    input        w,
    output       Y1
);

    // State codes: A=000 B=001 C=010 D=011 E=100 F=101
    reg [2:0] Y;

    always @(*) begin
        case (y)
            3'b000: Y = w ? 3'b000 : 3'b001; // A: w1->A, w0->B
            3'b001: Y = w ? 3'b011 : 3'b010; // B: w1->D, w0->C
            3'b010: Y = w ? 3'b011 : 3'b100; // C: w1->D, w0->E
            3'b011: Y = w ? 3'b000 : 3'b101; // D: w1->A, w0->F
            3'b100: Y = w ? 3'b011 : 3'b100; // E: w1->D, w0->E
            3'b101: Y = w ? 3'b011 : 3'b010; // F: w1->D, w0->C
            default: Y = 3'b000;
        endcase
    end

    assign Y1 = Y[1];

endmodule
