module TopModule (
    input  clk,
    input  areset,
    input  x,
    output z
);
    // One-hot encoding: A = 2'b01, B = 2'b10
    localparam A = 2'b01, B = 2'b10;
    reg [1:0] state = A;

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

    // Mealy output: A: z=x ; B: z=~x
    assign z = (state == B) ? ~x : x;
endmodule
