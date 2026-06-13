module TopModule(
    input  clk,
    input  areset,
    input  x,
    output z
);
    // One-hot states: A = 2'b01, B = 2'b10
    localparam A = 2'b01, B = 2'b10;
    reg [1:0] state;

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= A;
        else begin
            case (state)
                A: state <= x ? B : A;
                B: state <= B;
                default: state <= A;
            endcase
        end
    end

    // Mealy output: depends on state and x.
    // A: z = x ; B: z = ~x
    assign z = (state == A) ? x : ~x;
endmodule
