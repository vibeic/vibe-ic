module TopModule (
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

    // Mealy output:
    //   A,x=0 -> 0 ; A,x=1 -> 1 ; B,x=0 -> 1 ; B,x=1 -> 0
    reg z_r;
    always @(*) begin
        case (state)
            A: z_r = x ? 1'b1 : 1'b0;
            B: z_r = x ? 1'b0 : 1'b1;
            default: z_r = 1'b0;
        endcase
    end
    assign z = z_r;
endmodule
