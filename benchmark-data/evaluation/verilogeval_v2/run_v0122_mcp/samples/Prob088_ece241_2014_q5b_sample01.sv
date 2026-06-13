module TopModule (
    input  clk,
    input  areset,
    input  x,
    output z
);

    localparam A = 2'b01, B = 2'b10;
    reg [1:0] state;

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= A;
        else begin
            case (state)
                A:       state <= x ? B : A;
                B:       state <= B;
                default: state <= A;
            endcase
        end
    end

    // Mealy output: z = f(state, x)
    // A: x0->z0, x1->z1  => z = x
    // B: x0->z1, x1->z0  => z = ~x
    assign z = (state == A) ? x : ~x;

endmodule
