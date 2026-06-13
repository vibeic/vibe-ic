module TopModule (
    input  clk,
    input  reset,
    input  w,
    output z
);

    localparam A = 3'd0, B = 3'd1, C = 3'd2, D = 3'd3, E = 3'd4, F = 3'd5;

    reg [2:0] state, nxt;

    always @(*) begin
        case (state)
            A: nxt = w ? A : B;
            B: nxt = w ? D : C;
            C: nxt = w ? D : E;
            D: nxt = w ? A : F;
            E: nxt = w ? D : E;
            F: nxt = w ? D : C;
            default: nxt = A;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= nxt;
    end

    // Moore output: z=1 in states E and F
    assign z = (state == E) || (state == F);

endmodule
