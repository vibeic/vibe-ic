module TopModule (
    input  [2:0] y,
    input        w,
    output       Y1
);

    localparam A = 3'b000, B = 3'b001, C = 3'b010,
               D = 3'b011, E = 3'b100, F = 3'b101;

    reg [2:0] Y;

    always @(*) begin
        case (y)
            A: Y = w ? A : B;
            B: Y = w ? D : C;
            C: Y = w ? D : E;
            D: Y = w ? A : F;
            E: Y = w ? D : E;
            F: Y = w ? D : C;
            default: Y = A;
        endcase
    end

    assign Y1 = Y[1];

endmodule
