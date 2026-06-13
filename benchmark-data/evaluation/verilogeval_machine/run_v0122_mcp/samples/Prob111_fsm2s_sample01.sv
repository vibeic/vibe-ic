module TopModule (
    input  clk,
    input  j,
    input  k,
    input  reset,
    output out
);
    localparam A = 1'b0, B = 1'b1;
    reg state, next;

    // Combinational next-state logic
    always @(*) begin
        case (state)
            A: next = j ? B : A;
            B: next = k ? A : B;
            default: next = A;
        endcase
    end

    // Clocked state register with synchronous active-high reset to A
    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= next;
    end

    // Moore output: high only in state B
    assign out = (state == B);
endmodule
