module TopModule (
    input  clk,
    input  reset,
    input  w,
    output z
);

    localparam A = 3'd0;
    localparam B = 3'd1;
    localparam C = 3'd2;
    localparam D = 3'd3;
    localparam E = 3'd4;
    localparam F = 3'd5;

    // state table
    reg [2:0] state, next;

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

    // state flip-flops
    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= next;
    end

    assign z = (state == E) || (state == F);

endmodule
