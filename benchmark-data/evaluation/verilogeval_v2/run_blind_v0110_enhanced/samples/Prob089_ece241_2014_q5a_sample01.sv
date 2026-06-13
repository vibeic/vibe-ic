module TopModule(
    input  clk,
    input  areset,
    input  x,
    output z
);
    // Serial 2's complement, LSB first: copy bits up to & including the
    // first '1', then invert.  State = whether the first '1' has been seen.
    //   A (not seen yet): z = x ; on x=1 -> B
    //   B (already seen):  z = ~x ; stay in B
    localparam A = 1'b0, B = 1'b1;
    reg state;

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

    assign z = (state == A) ? x : ~x;
endmodule
