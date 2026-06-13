module TopModule(
    input  clk,
    input  areset,
    input  x,
    output z
);
    // One-hot encoding: state[0]=A, state[1]=B. Mealy output.
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

    // Mealy output: depends on current state and x.
    // A,x=0 -> z=0 ; A,x=1 -> z=1 ; B,x=0 -> z=1 ; B,x=1 -> z=0
    assign z = state[0] ? x : ~x;
endmodule
