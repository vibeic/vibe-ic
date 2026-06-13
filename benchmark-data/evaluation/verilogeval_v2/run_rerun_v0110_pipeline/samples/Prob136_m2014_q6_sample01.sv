module TopModule (
    input  clk,
    input  reset,
    input  w,
    output z
);
    localparam A = 3'd0, B = 3'd1, C = 3'd2, D = 3'd3, E = 3'd4, F = 3'd5;
    reg [2:0] state;

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else begin
            case (state)
                A: state <= w ? A : B;
                B: state <= w ? D : C;
                C: state <= w ? D : E;
                D: state <= w ? A : F;
                E: state <= w ? D : E;
                F: state <= w ? D : C;
                default: state <= A;
            endcase
        end
    end

    assign z = (state == E) || (state == F);
endmodule
