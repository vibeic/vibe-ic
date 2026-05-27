module TopModule(
    input        do_sub,
    input  [7:0] a,
    input  [7:0] b,
    output reg [7:0] out,
    output reg       result_is_zero
);
    // Bug fixes:
    //  1) original used `if (~out) result_is_zero=1;` which (a) is wrong logic
    //     (~out is truthy unless out==8'hFF) and (b) infers a latch because
    //     result_is_zero is never cleared. Drive it unconditionally as out==0.
    always @(*) begin
        case (do_sub)
            1'b0: out = a + b;
            1'b1: out = a - b;
            default: out = a + b;
        endcase
        result_is_zero = (out == 8'b0);
    end
endmodule
