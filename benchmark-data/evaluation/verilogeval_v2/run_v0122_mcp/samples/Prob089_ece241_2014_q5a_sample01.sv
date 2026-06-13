module TopModule (
    input  clk,
    input  areset,
    input  x,
    output z
);

    // Serial 2's complement, LSB first:
    //   pass bits through until (and including) the first 1, then invert.
    // State A: no 1 seen yet (still "copy" region) -> z = x, and on x=1 move to B.
    // State B: first 1 already seen -> invert -> z = ~x.
    localparam A = 1'b0, B = 1'b1;
    reg state;

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

    assign z = (state == A) ? x : ~x;

endmodule
