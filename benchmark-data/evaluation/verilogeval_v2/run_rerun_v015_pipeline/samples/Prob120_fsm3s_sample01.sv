module TopModule (
    input  clk,
    input  reset,
    input  in,
    output out
);
    localparam A = 2'b00, B = 2'b01, C = 2'b10, D = 2'b11;
    reg [1:0] state, next;

    always @(*) begin
        case (state)
            A: next = in ? B : A;
            B: next = in ? B : C;
            C: next = in ? D : A;
            D: next = in ? B : C;
            default: next = A;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= A;          // synchronous active-high reset to A
        else
            state <= next;
    end

    assign out = (state == D);   // Moore: D=>1, else 0
endmodule
