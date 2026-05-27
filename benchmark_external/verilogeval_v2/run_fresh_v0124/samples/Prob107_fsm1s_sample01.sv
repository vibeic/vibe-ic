module TopModule (
    input  clk,
    input  reset,
    input  in,
    output out
);
    localparam A = 1'b0, B = 1'b1;
    reg state, next;

    always @(*) begin
        case (state)
            A: next = in ? A : B;
            B: next = in ? B : A;
            default: next = B;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= B;
        else
            state <= next;
    end

    assign out = (state == B);
endmodule
