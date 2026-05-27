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
            A: next = in ? A : B;
            B: next = in ? B : A;
            default: next = B;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= B;          // asynchronous reset to B
        else
            state <= next;
    end

    assign out = (state == B);   // Moore: B=>1, A=>0
endmodule
