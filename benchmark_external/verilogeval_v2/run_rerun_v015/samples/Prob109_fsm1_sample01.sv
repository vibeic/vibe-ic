module TopModule (
    input  clk,
    input  areset,
    input  in,
    output out
);
    localparam A = 1'b0, B = 1'b1;
    reg state, next;

    always @(*) begin
        case (state)
            B: next = in ? B : A;
            A: next = in ? A : B;
            default: next = B;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= B;
        else
            state <= next;
    end

    assign out = (state == B);
endmodule
