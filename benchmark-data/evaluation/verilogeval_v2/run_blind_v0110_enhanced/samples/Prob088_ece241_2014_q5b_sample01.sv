module TopModule(
    input  clk,
    input  areset,
    input  x,
    output z
);
    // One-hot states: A = 2'b01, B = 2'b10
    localparam [1:0] A = 2'b01, B = 2'b10;
    reg [1:0] state;

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= A;
        else begin
            case (state)
                A: state <= x ? B : A;
                B: state <= B;          // once in B, stay in B
                default: state <= A;
            endcase
        end
    end

    // Mealy output:
    //  A,x=0 -> z=0 ; A,x=1 -> z=1
    //  B,x=0 -> z=1 ; B,x=1 -> z=0
    assign z = (state == A) ? x : ~x;
endmodule
