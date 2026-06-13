module TopModule (
    input  do_sub,
    input  [7:0] a,
    input  [7:0] b,
    output reg [7:0] out,
    output reg result_is_zero
);

    always @(*) begin
        case (do_sub)
            1'b0: out = a + b;
            1'b1: out = a - b;
            default: out = a + b;
        endcase

        // Bug fix:
        //  - test the whole result against zero (reduction), not bitwise ~out
        //  - drive result_is_zero on every path (no inferred latch)
        result_is_zero = (out == 8'b0);
    end

endmodule
