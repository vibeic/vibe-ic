module TopModule (
    input  clk,
    input  reset,
    input  w,
    output z
);

    localparam A = 3'd0, B = 3'd1, C = 3'd2, D = 3'd3, E = 3'd4, F = 3'd5;

    reg [2:0] state, nxt;

    // Combinational state table
    always @(*) begin
        case (state)
            A: nxt = w ? B : A;
            B: nxt = w ? C : D;
            C: nxt = w ? E : D;
            D: nxt = w ? F : A;
            E: nxt = w ? E : D;
            F: nxt = w ? C : D;
            default: nxt = A;
        endcase
    end

    // State flip-flops
    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= nxt;
    end

    // Moore output
    assign z = (state == E) || (state == F);

endmodule
