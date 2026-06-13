module TopModule (
    input        clk,
    input        resetn,
    input  [2:0] r,
    output [2:0] g
);
    localparam A = 2'd0;  // idle, no grant
    localparam B = 2'd1;  // g0
    localparam C = 2'd2;  // g1
    localparam D = 2'd3;  // g2

    reg [1:0] state, next;

    always @(*) begin
        case (state)
            A: begin
                if      (r[0])            next = B;
                else if (r[1])            next = C;
                else if (r[2])            next = D;
                else                      next = A;
            end
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
