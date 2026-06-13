module TopModule (
    input  [2:0] y,
    input  w,
    output Y1
);

    localparam A = 3'b000;
    localparam B = 3'b001;
    localparam C = 3'b010;
    localparam D = 3'b011;
    localparam E = 3'b100;
    localparam F = 3'b101;

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
