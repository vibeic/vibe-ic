module TopModule (
    input  clk,
    input  reset,
    input  in,
    output out
);

    localparam A = 1'b0, B = 1'b1;
    reg state, next_state;

    always @(*) begin
        case (state)
            B: next_state = in ? B : A;
            A: next_state = in ? A : B;
            default: next_state = B;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= B;
        else
            state <= next_state;
    end

    assign out = (state == B);

endmodule
