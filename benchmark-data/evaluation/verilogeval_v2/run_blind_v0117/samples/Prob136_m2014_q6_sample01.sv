module TopModule (
    input  clk,
    input  reset,
    input  w,
    output z
);
    localparam A=3'd0, B=3'd1, C=3'd2, D=3'd3, E=3'd4, F=3'd5;
    reg [2:0] state, nstate;

    always @(*) begin
        case (state)
            A: nstate = w ? A : B;
            B: nstate = w ? D : C;
            C: nstate = w ? D : E;
            D: nstate = w ? A : F;
            E: nstate = w ? D : E;
            F: nstate = w ? D : C;
            default: nstate = A;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= nstate;
    end

    // Moore output: 1 in states E and F only.
    assign z = (state == E) || (state == F);
endmodule
