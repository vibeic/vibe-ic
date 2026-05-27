module TopModule (
    input  clk,
    input  reset,
    input  w,
    output z
);

    localparam A = 3'd0, B = 3'd1, C = 3'd2, D = 3'd3, E = 3'd4, F = 3'd5;

    reg [2:0] state, next;

    // State diagram (output 1 in E and F):
    //  A: w1->B w0->A
    //  B: w1->C w0->D
    //  C: w1->E w0->D
    //  D: w1->F w0->A
    //  E: w1->E w0->D
    //  F: w1->C w0->D
    // Separate always blocks for state table and flip-flops.
    always @(*) begin
        case (state)
            A: next = w ? B : A;
            B: next = w ? C : D;
            C: next = w ? E : D;
            D: next = w ? F : A;
            E: next = w ? E : D;
            F: next = w ? C : D;
            default: next = A;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= next;
    end

    assign z = (state == E) || (state == F);

endmodule
