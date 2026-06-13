module TopModule (
    input  do_sub,
    input  [7:0] a,
    input  [7:0] b,
    output reg [7:0] out,
    output reg result_is_zero
);

    always @(*) begin
        // Bug fixes: drive out on every path (if/else, no missing case branch),
        // compare the whole result to zero (not bitwise ~), and assign
        // result_is_zero unconditionally to avoid an inferred latch.
        if (do_sub)
            out = a - b;
        else
            out = a + b;

        result_is_zero = (out == 8'b0);
    end

endmodule
