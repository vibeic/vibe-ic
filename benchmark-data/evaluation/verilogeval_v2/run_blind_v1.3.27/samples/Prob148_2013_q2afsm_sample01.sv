module TopModule(
    input  clk,
    input  resetn,
    input  [2:0] r,
    output [2:0] g
);
    localparam A=2'd0, B=2'd1, C=2'd2, D=2'd3;

    reg [1:0] state, next;

    always @(*) begin
        case (state)
            A: next = r[0] ? B : (r[1] ? C : (r[2] ? D : A));
            B: next = r[0] ? B : A;
            C: next = r[1] ? C : A;
            D: next = r[2] ? D : A;
            default: next = A;
        endcase
    end

    always @(posedge clk) begin
        if (!resetn) state <= A;
        else         state <= next;
    end

    assign g[0] = (state == B);
    assign g[1] = (state == C);
    assign g[2] = (state == D);

endmodule
