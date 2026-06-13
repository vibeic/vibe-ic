module TopModule (
    input  [2:0] y,
    input  w,
    output Y1
);
    reg [2:0] Y;

    always @(*) begin
        case (y)
            3'b000: Y = w ? 3'b000 : 3'b001; // A
            3'b001: Y = w ? 3'b011 : 3'b010; // B
            3'b010: Y = w ? 3'b011 : 3'b100; // C
            3'b011: Y = w ? 3'b000 : 3'b101; // D
            3'b100: Y = w ? 3'b011 : 3'b100; // E
            3'b101: Y = w ? 3'b011 : 3'b010; // F
            default: Y = 3'b000;
        endcase
    end

    assign Y1 = Y[1];
endmodule
