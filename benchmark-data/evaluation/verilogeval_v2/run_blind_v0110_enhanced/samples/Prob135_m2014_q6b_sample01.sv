module TopModule(
    input  [2:0] y,
    input        w,
    output       Y1
);
    // State codes: A=000 B=001 C=010 D=011 E=100 F=101
    reg [2:0] Y;
    always @(*) begin
        case (y)
            3'b000: Y = w ? 3'b000 : 3'b001; // A: w=0->B, w=1->A
            3'b001: Y = w ? 3'b011 : 3'b010; // B: w=0->C, w=1->D
            3'b010: Y = w ? 3'b011 : 3'b100; // C: w=0->E, w=1->D
            3'b011: Y = w ? 3'b000 : 3'b101; // D: w=0->F, w=1->A
            3'b100: Y = w ? 3'b011 : 3'b100; // E: w=0->E, w=1->D
            3'b101: Y = w ? 3'b011 : 3'b010; // F: w=0->C, w=1->D
            default: Y = 3'b000;
        endcase
    end

    assign Y1 = Y[1];
endmodule
