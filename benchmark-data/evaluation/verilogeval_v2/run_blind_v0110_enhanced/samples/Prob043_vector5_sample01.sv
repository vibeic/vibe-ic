module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    input  e,
    output [24:0] out
);
    // out[24]=~a^a, out[23]=~a^b, ... out[0]=~e^e
    // ~x ^ y == 1 when x == y (XNOR equality)
    wire [4:0] left  = {a, b, c, d, e};   // first operand index 4..0 -> a..e
    wire [4:0] right = {a, b, c, d, e};

    assign out = { ~left[4]^right[4], ~left[4]^right[3], ~left[4]^right[2], ~left[4]^right[1], ~left[4]^right[0],
                   ~left[3]^right[4], ~left[3]^right[3], ~left[3]^right[2], ~left[3]^right[1], ~left[3]^right[0],
                   ~left[2]^right[4], ~left[2]^right[3], ~left[2]^right[2], ~left[2]^right[1], ~left[2]^right[0],
                   ~left[1]^right[4], ~left[1]^right[3], ~left[1]^right[2], ~left[1]^right[1], ~left[1]^right[0],
                   ~left[0]^right[4], ~left[0]^right[3], ~left[0]^right[2], ~left[0]^right[1], ~left[0]^right[0] };
endmodule
