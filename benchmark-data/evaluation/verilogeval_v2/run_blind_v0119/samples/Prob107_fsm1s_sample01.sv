module TopModule (
    input  clk,
    input  reset,
    input  in,
    output out
);
    localparam A = 1'b0, B = 1'b1;
    reg state;

    always @(posedge clk) begin
        if (reset)
            state <= B;            // synchronous active-high reset to B
        else case (state)
            A: state <= in ? A : B;
            B: state <= in ? B : A;
            default: state <= B;
        endcase
    end

    // Moore output: out=1 in state B
    assign out = (state == B);
endmodule
