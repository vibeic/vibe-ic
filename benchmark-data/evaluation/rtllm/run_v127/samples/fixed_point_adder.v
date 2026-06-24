// fixed_point_adder: sign-magnitude fixed-point adder.
// MSB is the sign bit; the low N-1 bits are the magnitude (Q fractional bits).
//   - same sign  -> add magnitudes, keep the common sign.
//   - diff sign  -> subtract the smaller magnitude from the larger; sign follows
//     the larger operand; a zero result forces sign 0.
module fixed_point_adder #(
    parameter Q = 8,
    parameter N = 16
)(
    input  [N-1:0] a,
    input  [N-1:0] b,
    output [N-1:0] c
);

    reg [N-1:0] res;

    always @(*) begin
        if (a[N-1] == b[N-1]) begin
            // Same sign: add magnitudes, retain the sign.
            res[N-2:0] = a[N-2:0] + b[N-2:0];
            res[N-1]   = a[N-1];
        end
        else begin
            // Different sign: subtract the smaller magnitude from the larger.
            if (a[N-2:0] > b[N-2:0]) begin
                res[N-2:0] = a[N-2:0] - b[N-2:0];
                res[N-1]   = a[N-1];
            end
            else begin
                res[N-2:0] = b[N-2:0] - a[N-2:0];
                res[N-1]   = (b[N-2:0] == a[N-2:0]) ? 1'b0 : b[N-1];
            end
        end
    end

    assign c = res;

endmodule
